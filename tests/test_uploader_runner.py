"""Phase 5 — uploader.runner orchestration tests.

Covers: preflight matrix, pre-upload policy re-check (using upload-title
input), policy infra fail soft, missing transcript / output / publish_at,
approved-dir basename fallback, future-too-near pad persistence, success path
(orphan-marker + 10a + 10b + cleanup), 10a-failure preserved next-run safety,
dry-run isolation (no DB / no API / no OAuth), policy-rejection-in-dry-run
ordering, run_all clips_for_upload filter, orphan reconcile gate.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.policy_gate.evaluator import CheckResult, PolicyVerdict
from src.quota_ledger import QuotaLedger
from src.state import Repository, connect, initialize_schema
from src.uploader import orphan_marker
from src.uploader.runner import UploadOutcome, run_all, upload_one_clip
from tests.conftest import StubConfig


# ---- shared fixture ---------------------------------------------------------


def _setup(tmp_path, *, status="quality_pass", publish_at_utc=None,
           youtube_video_id=None, place_in_approved=False):
    cfg = StubConfig(tmp_path)
    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn); repo = Repository(conn)

    repo.discovery_upsert_video(
        video_id="v1", title="T", channel="MovieClipsChannel",
        duration_seconds=600, views=1000, likes=10, comments=2,
        published_at="2026-04-01T00:00:00Z",
        keyword="best movie scenes", virality_score=2.0,
    )
    repo.set_video_status("v1", "selected")

    # Transcript with words spanning [30, 60].
    transcripts = Path(cfg.paths.transcripts_dir)
    words = [
        {"start": 30.0 + (i * 0.5), "end": 30.4 + (i * 0.5),
         "word": f"w{i}", "probability": 0.95}
        for i in range(60)
    ]
    payload = {
        "schema_version": 1, "video_id": "v1",
        "model": "large-v3", "compute_type": "int8_float16",
        "duration_seconds": 600.0, "language": "en", "language_probability": 0.99,
        "segments": [{"start": 30.0, "end": 60.0, "text": "x", "words": words}],
    }
    (transcripts / "v1.json").write_text(json.dumps(payload), encoding="utf-8")

    # Rendered file lives in pending unless place_in_approved is set.
    if place_in_approved:
        target_dir = Path(cfg.paths.approved_dir)
    else:
        target_dir = Path(cfg.paths.pending_dir)
    pending_path = target_dir / "__unscheduled__v1_30_60__cool.mp4"
    pending_path.write_bytes(b"\x00" * 4096)
    # If approved-dir, the DB row's output_path STILL points at pending (Phase 6
    # owns updating it; we want the basename fallback to find the file).
    db_output_path = Path(cfg.paths.pending_dir) / "__unscheduled__v1_30_60__cool.mp4"

    repo.upsert_selector_clip(
        clip_id="v1_30_60", video_id="v1",
        start_s=30.0, end_s=60.0,
        hook="iconic line", suggested_title="Cool Title",
        selection_method="heatmap_aided",
    )
    extras = {"output_path": str(db_output_path), "title_slug": "cool"}
    if publish_at_utc is not None:
        extras["publish_at_utc"] = publish_at_utc
    if youtube_video_id is not None:
        extras["youtube_video_id"] = youtube_video_id
    repo.set_clip_status("v1_30_60", status, **extras)

    return cfg, repo, pending_path


def _ledger(repo, ceiling=9000):
    return QuotaLedger(repo.conn, ceiling_units=ceiling)


def _youtube_returning(video_id="YT_NEW"):
    youtube = MagicMock()
    request = MagicMock()
    request.next_chunk.return_value = (None, {"id": video_id})
    youtube.videos.return_value.insert.return_value = request
    return youtube


def _passing_verdict():
    return PolicyVerdict(passed=True, checks=[
        CheckResult(name="banlist", passed=True, value="-"),
    ])


def _patch_evaluate(monkeypatch, verdict):
    """Patch evaluate_clip_policy in runner module to return `verdict`."""
    monkeypatch.setattr(
        "src.uploader.runner.evaluate_clip_policy",
        lambda *args, **kw: verdict,
    )


# ---- preflight matrix --------------------------------------------------------


def test_already_uploaded_skips(tmp_path, monkeypatch):
    cfg, repo, _ = _setup(
        tmp_path, status="uploaded", youtube_video_id="EXISTING_YT_ID",
        publish_at_utc="2026-05-04T13:00:00Z",
    )
    _patch_evaluate(monkeypatch, _passing_verdict())
    youtube = _youtube_returning()
    with patch("src.uploader.resumable.MediaFileUpload"):
        res = upload_one_clip(
            repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=youtube,
            clip_id="v1_30_60",
        )
    assert res.outcome == UploadOutcome.skipped_already_uploaded
    # No API call made.
    assert youtube.videos.return_value.insert.return_value.next_chunk.call_count == 0


def test_youtube_id_set_on_quality_pass_still_skips(tmp_path):
    """Defensive: even if status is regressed but yt_id is set, skip."""
    cfg, repo, _ = _setup(
        tmp_path, status="quality_pass", youtube_video_id="EXISTING_YT_ID",
        publish_at_utc="2026-05-04T13:00:00Z",
    )
    youtube = _youtube_returning()
    with patch("src.uploader.resumable.MediaFileUpload"):
        res = upload_one_clip(
            repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=youtube,
            clip_id="v1_30_60",
        )
    assert res.outcome == UploadOutcome.skipped_already_uploaded


def test_wrong_status_skips(tmp_path):
    cfg, repo, _ = _setup(
        tmp_path, status="rejected_quality",
        publish_at_utc="2026-05-04T13:00:00Z",
    )
    res = upload_one_clip(
        repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=_youtube_returning(),
        clip_id="v1_30_60",
    )
    assert res.outcome == UploadOutcome.skipped_wrong_status


# ---- file resolution ---------------------------------------------------------


def test_approved_status_uses_basename_fallback_to_approved_dir(tmp_path, monkeypatch):
    """Phase 6 may not have updated clips.output_path after the user moved the
    file from pending → approved. Resolution should still find it.
    """
    publish_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg, repo, _ = _setup(
        tmp_path, status="approved", publish_at_utc=publish_at,
        place_in_approved=True,
    )
    _patch_evaluate(monkeypatch, _passing_verdict())
    youtube = _youtube_returning()
    with patch("src.uploader.resumable.MediaFileUpload"):
        res = upload_one_clip(
            repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=youtube,
            clip_id="v1_30_60",
        )
    assert res.outcome == UploadOutcome.uploaded


def test_missing_output_returns_error(tmp_path, monkeypatch):
    publish_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg, repo, pending_path = _setup(
        tmp_path, status="quality_pass", publish_at_utc=publish_at,
    )
    pending_path.unlink()
    _patch_evaluate(monkeypatch, _passing_verdict())
    res = upload_one_clip(
        repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=_youtube_returning(),
        clip_id="v1_30_60",
    )
    assert res.outcome == UploadOutcome.error_no_output


def test_missing_publish_at_returns_error(tmp_path, monkeypatch):
    cfg, repo, _ = _setup(tmp_path, status="quality_pass", publish_at_utc=None)
    _patch_evaluate(monkeypatch, _passing_verdict())
    res = upload_one_clip(
        repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=_youtube_returning(),
        clip_id="v1_30_60",
    )
    assert res.outcome == UploadOutcome.error_no_publish_at


def test_missing_transcript_returns_error(tmp_path, monkeypatch):
    publish_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg, repo, _ = _setup(tmp_path, status="quality_pass", publish_at_utc=publish_at)
    (Path(cfg.paths.transcripts_dir) / "v1.json").unlink()
    _patch_evaluate(monkeypatch, _passing_verdict())
    res = upload_one_clip(
        repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=_youtube_returning(),
        clip_id="v1_30_60",
    )
    assert res.outcome == UploadOutcome.error_no_transcript


# ---- policy re-check ---------------------------------------------------------


def test_policy_recheck_rejection_flips_to_rejected_policy(tmp_path, monkeypatch):
    publish_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg, repo, _ = _setup(tmp_path, status="quality_pass", publish_at_utc=publish_at)
    bad = PolicyVerdict(
        passed=False, failed_check="banlist", failed_value="podcast",
        checks=[CheckResult(name="banlist", passed=False, value="podcast")],
    )
    _patch_evaluate(monkeypatch, bad)
    youtube = _youtube_returning()
    with patch("src.uploader.resumable.MediaFileUpload"):
        res = upload_one_clip(
            repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=youtube,
            clip_id="v1_30_60",
        )
    assert res.outcome == UploadOutcome.rejected_policy_recheck
    assert res.failed_check == "banlist"
    row = repo.conn.execute(
        "SELECT status, rejection_reason FROM clips WHERE clip_id=?", ("v1_30_60",),
    ).fetchone()
    assert row["status"] == "rejected_policy"
    assert "banlist:podcast" in row["rejection_reason"]
    # No API call.
    assert youtube.videos.return_value.insert.return_value.next_chunk.call_count == 0


def test_policy_recheck_uses_hook_or_suggested_title_as_input(tmp_path, monkeypatch):
    """Regression: the title input passed to evaluate_clip_policy must match
    what build_title uses for the actual upload (hook OR suggested_title).
    """
    publish_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg, repo, _ = _setup(tmp_path, status="quality_pass", publish_at_utc=publish_at)
    captured = {}
    def _capture(cfg_arg, clip_text, suggested_title, *, ollama_host=None):
        captured["title"] = suggested_title
        return _passing_verdict()
    monkeypatch.setattr("src.uploader.runner.evaluate_clip_policy", _capture)
    with patch("src.uploader.resumable.MediaFileUpload"):
        upload_one_clip(
            repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=_youtube_returning(),
            clip_id="v1_30_60",
        )
    # Hook is "iconic line" (set in _setup); that's what build_title would use.
    assert captured["title"] == "iconic line"


def test_policy_infra_fail_soft_leaves_clip_at_quality_pass(tmp_path, monkeypatch):
    publish_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg, repo, _ = _setup(tmp_path, status="quality_pass", publish_at_utc=publish_at)
    infra = PolicyVerdict(
        passed=False, infrastructure_failed=True,
        infrastructure_reason="nsfw:network_error",
    )
    _patch_evaluate(monkeypatch, infra)
    res = upload_one_clip(
        repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=_youtube_returning(),
        clip_id="v1_30_60",
    )
    assert res.outcome == UploadOutcome.infrastructure_failed
    row = repo.conn.execute(
        "SELECT status FROM clips WHERE clip_id=?", ("v1_30_60",),
    ).fetchone()
    assert row["status"] == "quality_pass"  # unchanged


# ---- happy path: orphan marker + 10a + 10b -----------------------------------


def test_success_writes_marker_then_db_then_unlinks_marker(tmp_path, monkeypatch):
    publish_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg, repo, _ = _setup(tmp_path, status="quality_pass", publish_at_utc=publish_at)
    _patch_evaluate(monkeypatch, _passing_verdict())
    youtube = _youtube_returning("YT_NEW_42")

    with patch("src.uploader.resumable.MediaFileUpload"):
        res = upload_one_clip(
            repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=youtube,
            clip_id="v1_30_60",
        )
    assert res.outcome == UploadOutcome.uploaded
    assert res.youtube_video_id == "YT_NEW_42"

    # DB state
    row = repo.conn.execute(
        "SELECT status, youtube_video_id, publish_at_utc FROM clips WHERE clip_id=?",
        ("v1_30_60",),
    ).fetchone()
    assert row["status"] == "uploaded"
    assert row["youtube_video_id"] == "YT_NEW_42"
    assert row["publish_at_utc"].endswith("Z")
    upload_row = repo.conn.execute(
        "SELECT youtube_video_id, quota_units_used FROM uploads WHERE clip_id=?",
        ("v1_30_60",),
    ).fetchone()
    assert upload_row["youtube_video_id"] == "YT_NEW_42"
    assert upload_row["quota_units_used"] == 1600

    # Orphan marker cleaned up.
    orphans_dir = Path(cfg.paths.orphans_dir)
    assert not (orphans_dir / "v1_30_60.json").exists()


def test_step_10a_failure_leaves_marker_so_next_run_is_safe(tmp_path, monkeypatch):
    """If set_clip_youtube_id raises, the marker file persists. A subsequent
    run's reconcile gate aborts with orphan_reconcile_required, preventing
    the duplicate-upload risk.
    """
    publish_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg, repo, _ = _setup(tmp_path, status="quality_pass", publish_at_utc=publish_at)
    _patch_evaluate(monkeypatch, _passing_verdict())
    youtube = _youtube_returning("YT_42")

    # Sabotage the 10a write.
    original = repo.set_clip_youtube_id
    def _raise(*a, **kw):
        raise sqlite3.OperationalError("simulated 10a failure")
    monkeypatch.setattr(repo, "set_clip_youtube_id", _raise)

    with patch("src.uploader.resumable.MediaFileUpload"):
        res = upload_one_clip(
            repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=youtube,
            clip_id="v1_30_60",
        )
    assert res.outcome == UploadOutcome.error_persist_failed
    # Marker present.
    orphans_dir = Path(cfg.paths.orphans_dir)
    assert (orphans_dir / "v1_30_60.json").exists()

    # Restore the helper and run reconcile_orphans — DB has no yt_id, no
    # uploads row → marker is INCONSISTENT → run_all returns []
    monkeypatch.setattr(repo, "set_clip_youtube_id", original)
    results = run_all(
        repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=youtube,
    )
    assert results == []
    # Marker must still be there until the user reconciles.
    assert (orphans_dir / "v1_30_60.json").exists()


def test_future_too_near_pad_persists_padded_value(tmp_path, monkeypatch):
    """publish_at_utc 5 min from now → padded to now + 20 min, persisted."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    near = (now + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg, repo, _ = _setup(tmp_path, status="quality_pass", publish_at_utc=near)
    _patch_evaluate(monkeypatch, _passing_verdict())
    with patch("src.uploader.resumable.MediaFileUpload"):
        res = upload_one_clip(
            repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=_youtube_returning(),
            clip_id="v1_30_60", now_utc=now,
        )
    assert res.outcome == UploadOutcome.uploaded
    assert res.was_padded is True
    expected = (now + timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert res.padded_publish_at == expected
    row = repo.conn.execute(
        "SELECT publish_at_utc FROM clips WHERE clip_id=?", ("v1_30_60",),
    ).fetchone()
    assert row["publish_at_utc"] == expected


# ---- dry-run isolation -------------------------------------------------------


def test_dry_run_writes_json_no_db_no_api(tmp_path, monkeypatch):
    publish_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg, repo, _ = _setup(tmp_path, status="quality_pass", publish_at_utc=publish_at)
    _patch_evaluate(monkeypatch, _passing_verdict())
    youtube = _youtube_returning()
    res = upload_one_clip(
        repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=youtube,
        clip_id="v1_30_60", dry_run=True,
    )
    assert res.outcome == UploadOutcome.dry_run
    # File written.
    dry_run_path = Path(cfg.paths.dry_run_dir) / "v1_30_60.json"
    assert dry_run_path.exists()
    body = json.loads(dry_run_path.read_text())
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["publishAt"].endswith("Z")
    assert "+00:00" not in body["status"]["publishAt"]
    # No API call.
    assert youtube.videos.return_value.insert.return_value.next_chunk.call_count == 0
    # No DB writes (status unchanged, no uploads row, no orphan marker).
    row = repo.conn.execute(
        "SELECT status, youtube_video_id FROM clips WHERE clip_id=?", ("v1_30_60",),
    ).fetchone()
    assert row["status"] == "quality_pass"
    assert row["youtube_video_id"] is None
    upl = repo.conn.execute("SELECT * FROM uploads WHERE clip_id=?", ("v1_30_60",)).fetchone()
    assert upl is None
    orphans = list(Path(cfg.paths.orphans_dir).iterdir())
    assert orphans == []


def test_dry_run_policy_rejection_emits_no_json(tmp_path, monkeypatch):
    """Ordering regression: policy re-check runs BEFORE dry-run JSON emission,
    so a content-failing clip in dry-run reports rejected_policy_recheck and
    the dry_run JSON file is NOT written.
    """
    publish_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg, repo, _ = _setup(tmp_path, status="quality_pass", publish_at_utc=publish_at)
    bad = PolicyVerdict(
        passed=False, failed_check="banlist", failed_value="badword",
    )
    _patch_evaluate(monkeypatch, bad)
    res = upload_one_clip(
        repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=_youtube_returning(),
        clip_id="v1_30_60", dry_run=True,
    )
    assert res.outcome == UploadOutcome.rejected_policy_recheck
    dry_run_path = Path(cfg.paths.dry_run_dir) / "v1_30_60.json"
    assert not dry_run_path.exists()
    # Dry-run mode: status NOT flipped.
    row = repo.conn.execute(
        "SELECT status FROM clips WHERE clip_id=?", ("v1_30_60",),
    ).fetchone()
    assert row["status"] == "quality_pass"


# ---- Slice 9: AI-gen dry-run integration -------------------------------------


def _setup_ai_gen(tmp_path, *, publish_at_utc=None):
    """Set up an ai_generated clip with a linked script row for dry-run tests."""
    cfg = StubConfig(tmp_path)
    db = Path(cfg.paths.state_db)
    conn = connect(db)
    initialize_schema(conn)
    repo = Repository(conn)

    # Insert a topic + script row.
    topic_id = repo.insert_topic(
        url="https://example.com/gpt5",
        title="GPT-5 Released",
        source_feed="https://feeds.example.com",
        fetched_at="2026-05-22T10:00:00Z",
    )
    repo.insert_script(
        script_id="sc-ai-test",
        topic_id=topic_id,
        title="GPT-5 Is Here",
        narration="OpenAI just dropped GPT-5 and it hits different.",
        shots_json='[]',
        style_suffix="clean editorial",
        ollama_model="qwen2.5:3b-instruct",
        created_at="2026-05-22T10:00:00Z",
        category="ai-models",
    )

    # Insert the ai_generated clip row directly (upsert_selector_clip sets sourced).
    publish_at = publish_at_utc or (
        (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    pending_path = Path(cfg.paths.pending_dir) / "ai-clip-1.mp4"
    pending_path.write_bytes(b"\x00" * 4096)
    conn.execute("""
        INSERT INTO clips (
            clip_id, video_id, start_s, end_s, hook, suggested_title,
            selection_method, status, content_kind, script_id,
            output_path, publish_at_utc
        ) VALUES (
            'ai-clip-1', NULL, 0.0, 16.0, 'GPT-5 is here', 'GPT-5 Analysis',
            'ai_generated', 'quality_pass', 'ai_generated', 'sc-ai-test',
            :output_path, :publish_at
        )
    """, {"output_path": str(pending_path), "publish_at": publish_at})
    conn.commit()

    return cfg, repo


def test_ai_gen_dry_run_writes_disclosure_flag(tmp_path, monkeypatch):
    cfg, repo = _setup_ai_gen(tmp_path)
    _patch_evaluate(monkeypatch, _passing_verdict())

    res = upload_one_clip(
        repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=None,
        clip_id="ai-clip-1", dry_run=True,
        now_utc=datetime.now(timezone.utc),
    )

    assert res.outcome == UploadOutcome.dry_run
    dry_run_path = Path(cfg.paths.dry_run_dir) / "ai-clip-1.json"
    assert dry_run_path.exists()
    body = json.loads(dry_run_path.read_text())
    assert body["status"]["containsSyntheticMedia"] is True


def test_ai_gen_dry_run_description_has_footer_not_source(tmp_path, monkeypatch):
    cfg, repo = _setup_ai_gen(tmp_path)
    _patch_evaluate(monkeypatch, _passing_verdict())

    upload_one_clip(
        repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=None,
        clip_id="ai-clip-1", dry_run=True,
        now_utc=datetime.now(timezone.utc),
    )

    body = json.loads((Path(cfg.paths.dry_run_dir) / "ai-clip-1.json").read_text())
    desc = body["snippet"]["description"]
    assert "Made with AI. For entertainment / educational use." in desc
    assert "Source:" not in desc
    assert "Original channel:" not in desc


def test_ai_gen_dry_run_tags_seeded_from_category(tmp_path, monkeypatch):
    cfg, repo = _setup_ai_gen(tmp_path)
    _patch_evaluate(monkeypatch, _passing_verdict())

    upload_one_clip(
        repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=None,
        clip_id="ai-clip-1", dry_run=True,
        now_utc=datetime.now(timezone.utc),
    )

    body = json.loads((Path(cfg.paths.dry_run_dir) / "ai-clip-1.json").read_text())
    assert body["snippet"]["tags"][0] == "aimodels"


# ---- run_all + reconcile gate ------------------------------------------------


def test_run_all_filters_to_clips_for_upload(tmp_path, monkeypatch):
    """Only quality_pass + approved clips with publish_at_utc + null
    youtube_video_id are picked up.
    """
    publish_at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg, repo, _ = _setup(tmp_path, status="quality_pass", publish_at_utc=publish_at)
    # Add a rejected_quality clip too — should be excluded.
    repo.upsert_selector_clip(
        clip_id="v1_70_100", video_id="v1",
        start_s=70.0, end_s=100.0, hook="x", suggested_title="x",
        selection_method="transcript_only",
    )
    repo.set_clip_status("v1_70_100", "rejected_quality")

    _patch_evaluate(monkeypatch, _passing_verdict())
    with patch("src.uploader.resumable.MediaFileUpload"):
        results = run_all(
            repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=_youtube_returning(),
        )
    assert len(results) == 1
    assert results[0].clip_id == "v1_30_60"


def test_orphan_reconcile_inconsistent_aborts_run_all(tmp_path):
    cfg, repo, _ = _setup(tmp_path, status="quality_pass",
                          publish_at_utc="2026-05-04T13:00:00Z")
    # Drop an INCONSISTENT marker into output/orphans/.
    orphans_dir = Path(cfg.paths.orphans_dir)
    (orphans_dir / "v1_30_60.json").write_text(json.dumps({
        "clip_id": "v1_30_60",
        "youtube_video_id": "ORPHAN_YT",
        "padded_publish_at_utc": "2026-05-04T13:00:00Z",
        "quota_units_used": 1600,
        "uploaded_at_utc": "2026-05-04T12:50:00Z",
    }), encoding="utf-8")

    results = run_all(
        repo=repo, cfg=cfg, ledger=_ledger(repo), youtube=_youtube_returning(),
    )
    assert results == []
    # Marker still there — reconcile MUST be manual.
    assert (orphans_dir / "v1_30_60.json").exists()
    # Alert appended.
    alerts_path = Path(cfg.paths.logs_dir) / "alerts.md"
    assert alerts_path.exists()
    assert "orphan_reconcile_required" in alerts_path.read_text(encoding="utf-8")
