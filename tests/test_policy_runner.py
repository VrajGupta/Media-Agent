"""policy_gate runner: status transitions, preflight matrix, batch alerts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.policy_gate import evaluator as ev_mod
from src.policy_gate import runner as runner_mod
from src.policy_gate.evaluator import PolicyVerdict, CheckResult
from src.policy_gate.hook_sanity import HookSanityVerdict
from src.policy_gate.nsfw import NsfwVerdict
from src.policy_gate.runner import PolicyOutcome, gate_one_clip, run_all
from src.state import Repository, connect, initialize_schema
from tests.conftest import StubConfig


def _setup(tmp_path, *, banlist=None):
    cfg = StubConfig(tmp_path, banlist=banlist or [])
    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn); repo = Repository(conn)

    repo.discovery_upsert_video(
        video_id="v1", title="T", channel="C",
        duration_seconds=600, views=100, likes=1, comments=1,
        published_at="2026-04-01T00:00:00Z",
        keyword="k", virality_score=1.5,
    )
    repo.set_video_status("v1", "selected")

    transcripts = Path(cfg.paths.transcripts_dir)
    payload = {
        "schema_version": 1, "video_id": "v1",
        "model": "large-v3", "compute_type": "int8_float16",
        "duration_seconds": 600.0, "language": "en", "language_probability": 0.99,
        "segments": [
            {"start": 30.0, "end": 35.0, "text": "this is a clean clip with words",
             "words": [
                 {"start": 30.0, "end": 30.5, "word": "this", "probability": 0.9},
                 {"start": 30.5, "end": 31.0, "word": "is", "probability": 0.9},
                 {"start": 31.0, "end": 31.5, "word": "a", "probability": 0.9},
                 {"start": 31.5, "end": 32.0, "word": "clean", "probability": 0.9},
                 {"start": 32.0, "end": 32.5, "word": "clip", "probability": 0.9},
                 {"start": 32.5, "end": 33.0, "word": "with", "probability": 0.9},
                 {"start": 33.0, "end": 33.5, "word": "words", "probability": 0.9},
             ]}
        ],
    }
    (transcripts / "v1.json").write_text(json.dumps(payload), encoding="utf-8")
    return cfg, repo


def _seed_clip(repo, *, clip_id="v1_30_60", status="selected", suggested_title="Cool Title",
               publish_at_utc=None, youtube_video_id=None, output_path=None):
    repo.upsert_selector_clip(
        clip_id=clip_id, video_id="v1",
        start_s=30.0, end_s=60.0,
        hook="h", suggested_title=suggested_title,
        selection_method="heatmap_aided",
    )
    extras = {}
    if publish_at_utc is not None:
        extras["publish_at_utc"] = publish_at_utc
    if youtube_video_id is not None:
        extras["youtube_video_id"] = youtube_video_id
    if output_path is not None:
        extras["output_path"] = output_path
    repo.set_clip_status(clip_id, status, **extras)


def _patch_evaluator(monkeypatch, verdict: PolicyVerdict):
    monkeypatch.setattr(runner_mod, "evaluate_clip_policy", lambda *a, **kw: verdict)


# ---- preflight matrix -------------------------------------------------------


def test_selected_clip_is_gated(monkeypatch, tmp_path):
    cfg, repo = _setup(tmp_path)
    _seed_clip(repo)
    _patch_evaluator(monkeypatch, PolicyVerdict(passed=True, checks=[]))

    res = gate_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert res.outcome == PolicyOutcome.policy_pass

    row = repo.conn.execute("SELECT status FROM clips WHERE clip_id=?", ("v1_30_60",)).fetchone()
    assert row["status"] == "policy_pass"


def test_already_gated_clip_skips_without_force(monkeypatch, tmp_path):
    cfg, repo = _setup(tmp_path)
    _seed_clip(repo, status="policy_pass")

    # Evaluator must NOT be called.
    monkeypatch.setattr(
        runner_mod, "evaluate_clip_policy",
        lambda *a, **kw: pytest.fail("evaluator should not be called"),
    )
    res = gate_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert res.outcome == PolicyOutcome.skipped_already_gated


def test_already_rejected_clip_skips_without_force(monkeypatch, tmp_path):
    cfg, repo = _setup(tmp_path)
    _seed_clip(repo, status="rejected_policy")
    monkeypatch.setattr(
        runner_mod, "evaluate_clip_policy",
        lambda *a, **kw: pytest.fail("evaluator should not be called"),
    )
    res = gate_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert res.outcome == PolicyOutcome.skipped_already_gated


def test_force_re_gates_policy_pass(monkeypatch, tmp_path):
    cfg, repo = _setup(tmp_path)
    _seed_clip(repo, status="policy_pass")
    _patch_evaluator(monkeypatch, PolicyVerdict(
        passed=False, failed_check="banlist", failed_value="suicide",
    ))
    res = gate_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", force=True)
    assert res.outcome == PolicyOutcome.rejected_policy
    row = repo.conn.execute("SELECT status, rejection_reason FROM clips WHERE clip_id=?",
                            ("v1_30_60",)).fetchone()
    assert row["status"] == "rejected_policy"
    assert row["rejection_reason"] == "banlist:suicide"


def test_rendered_clip_is_locked(monkeypatch, tmp_path):
    """The CLI never re-gates a rendered clip — Phase 5's pre-upload
    re-check uses evaluate_clip_policy directly instead."""
    cfg, repo = _setup(tmp_path)
    _seed_clip(repo, status="rendered", output_path="output/pending/x.mp4")
    monkeypatch.setattr(
        runner_mod, "evaluate_clip_policy",
        lambda *a, **kw: pytest.fail("evaluator should not be called"),
    )
    res = gate_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert res.outcome == PolicyOutcome.skipped_locked


def test_uploaded_clip_is_locked_even_with_force(monkeypatch, tmp_path):
    cfg, repo = _setup(tmp_path)
    _seed_clip(repo, status="uploaded", youtube_video_id="abc123")
    monkeypatch.setattr(
        runner_mod, "evaluate_clip_policy",
        lambda *a, **kw: pytest.fail("evaluator should not be called"),
    )
    res = gate_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", force=True)
    assert res.outcome == PolicyOutcome.skipped_locked


# ---- transition rules -------------------------------------------------------


def test_pass_transitions_to_policy_pass_with_null_reason(monkeypatch, tmp_path):
    cfg, repo = _setup(tmp_path)
    _seed_clip(repo)
    # Pre-set a stale rejection_reason to verify it's cleared.
    repo.conn.execute(
        "UPDATE clips SET rejection_reason=? WHERE clip_id=?",
        ("stale", "v1_30_60"),
    )
    _patch_evaluator(monkeypatch, PolicyVerdict(passed=True, checks=[]))

    gate_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")

    row = repo.conn.execute(
        "SELECT status, rejection_reason FROM clips WHERE clip_id=?", ("v1_30_60",)
    ).fetchone()
    assert row["status"] == "policy_pass"
    assert row["rejection_reason"] is None


def test_fail_transitions_to_rejected_policy_with_check_value_reason(monkeypatch, tmp_path):
    cfg, repo = _setup(tmp_path)
    _seed_clip(repo)
    _patch_evaluator(monkeypatch, PolicyVerdict(
        passed=False, failed_check="profanity", failed_value="7.2",
    ))
    gate_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    row = repo.conn.execute(
        "SELECT status, rejection_reason FROM clips WHERE clip_id=?", ("v1_30_60",)
    ).fetchone()
    assert row["status"] == "rejected_policy"
    assert row["rejection_reason"] == "profanity:7.2"


def test_infrastructure_failure_leaves_clip_at_selected(monkeypatch, tmp_path):
    """Ollama unreachable / unknown label → fail-soft. Clip stays at 'selected'
    so the next run can retry; alert appended at run-end."""
    cfg, repo = _setup(tmp_path)
    _seed_clip(repo, status="selected")
    _patch_evaluator(monkeypatch, PolicyVerdict(
        passed=False, infrastructure_failed=True,
        infrastructure_reason="nsfw:ollama unreachable",
    ))
    res = gate_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert res.outcome == PolicyOutcome.infrastructure_failed
    row = repo.conn.execute(
        "SELECT status FROM clips WHERE clip_id=?", ("v1_30_60",)
    ).fetchone()
    assert row["status"] == "selected"


def test_missing_transcript_returns_error_no_transcript(tmp_path):
    cfg, repo = _setup(tmp_path)
    _seed_clip(repo)
    # Delete the transcript.
    Path(cfg.paths.transcripts_dir, "v1.json").unlink()
    res = gate_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert res.outcome == PolicyOutcome.error_no_transcript
    row = repo.conn.execute(
        "SELECT status FROM clips WHERE clip_id=?", ("v1_30_60",)
    ).fetchone()
    assert row["status"] == "selected"  # unchanged


def test_dry_run_does_not_write_db(monkeypatch, tmp_path):
    cfg, repo = _setup(tmp_path)
    _seed_clip(repo)
    _patch_evaluator(monkeypatch, PolicyVerdict(passed=True, checks=[]))
    gate_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", dry_run=True)
    row = repo.conn.execute(
        "SELECT status FROM clips WHERE clip_id=?", ("v1_30_60",)
    ).fetchone()
    assert row["status"] == "selected"


# ---- run_all ----------------------------------------------------------------


def test_run_all_filters_to_selected_status(monkeypatch, tmp_path):
    cfg, repo = _setup(tmp_path)
    _seed_clip(repo, clip_id="a", status="selected")
    _seed_clip(repo, clip_id="b", status="rendered")
    _seed_clip(repo, clip_id="c", status="rejected_policy")

    seen_ids = []

    def fake_eval(cfg_, ct, st, **kw):
        seen_ids.append("called")
        return PolicyVerdict(passed=True, checks=[])

    monkeypatch.setattr(runner_mod, "evaluate_clip_policy", fake_eval)

    results = run_all(repo, cfg)
    # Only the selected clip should be processed.
    processed = [r for r in results if r.outcome == PolicyOutcome.policy_pass]
    assert len(processed) == 1
    assert processed[0].clip_id == "a"
    assert len(seen_ids) == 1


def test_run_all_appends_infra_alert_on_repeated_ollama_failure(monkeypatch, tmp_path):
    cfg, repo = _setup(tmp_path)
    _seed_clip(repo)
    _patch_evaluator(monkeypatch, PolicyVerdict(
        passed=False, infrastructure_failed=True,
        infrastructure_reason="nsfw:ollama unreachable",
    ))

    run_all(repo, cfg)

    alerts_path = Path(cfg.paths.logs_dir) / "alerts.md"
    assert alerts_path.exists()
    body = alerts_path.read_text(encoding="utf-8")
    assert "policy_ollama_unreachable" in body
