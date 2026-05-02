"""Rejected-file relocation contract.

Best-effort consistency: filesystem move + DB are NOT atomic. We test each
failure-mode branch independently and assert the post-state is recoverable.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.quality_screen import runner as runner_mod
from src.quality_screen.runner import QualityOutcome, screen_one_clip
from src.state import Repository, connect, initialize_schema
from tests.conftest import StubConfig


def _setup(tmp_path):
    cfg = StubConfig(tmp_path)
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
            {"start": 30.0, "end": 35.0, "text": "x",
             "words": [{"start": 30.0, "end": 30.5, "word": "x", "probability": 0.9}]}
        ],
    }
    (transcripts / "v1.json").write_text(json.dumps(payload), encoding="utf-8")

    pending_path = Path(cfg.paths.pending_dir) / "__unscheduled__v1_30_60__cool.mp4"
    pending_path.write_bytes(b"\x00" * 4096)

    repo.upsert_selector_clip(
        clip_id="v1_30_60", video_id="v1",
        start_s=30.0, end_s=60.0,
        hook="h", suggested_title="Cool",
        selection_method="heatmap_aided",
    )
    repo.set_clip_status(
        "v1_30_60", "rendered",
        output_path=str(pending_path), title_slug="cool",
    )
    return cfg, repo, pending_path


def _rig_for_failure(monkeypatch, *, duration_s=33.6, density_words=10, dup_match=False):
    """Wire all probes to make exactly one check fail (density), so the
    runner enters the rejection / relocation branch."""
    from src.quality_screen import (
        density as density_mod,
        duration as duration_mod_,
        loudness as loudness_mod,
        dedup as dedup_mod,
    )

    monkeypatch.setattr(duration_mod_, "probe_duration", lambda p: duration_s)
    monkeypatch.setattr(loudness_mod, "measure_loudness",
                        lambda p: loudness_mod.LoudnessMeasurement(input_i=-14.0))
    monkeypatch.setattr(
        dedup_mod, "compute_signals",
        lambda p, d: dedup_mod.DedupSignals(phashes=[], audio_fp=None),
    )
    if dup_match:
        from src.quality_screen.dedup import DedupMatch
        monkeypatch.setattr(
            dedup_mod, "find_phash_match",
            lambda c, s, **kw: DedupMatch(matching_clip_id="prev", hamming_distance=2),
        )


def test_relocate_success_then_db_success(monkeypatch, tmp_path):
    cfg, repo, pending_path = _setup(tmp_path)
    _rig_for_failure(monkeypatch)
    # Force a content-fail on density: pass empty word window via duration mismatch.
    # Default cfg.min_speech_density=1.5; transcript has 1 word in [30,60] → 1/30 = 0.033 wps → reject.

    res = screen_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert res.outcome == QualityOutcome.rejected_quality

    # File no longer in pending; lives in rejected.
    assert not pending_path.exists()
    rejected_path = Path(cfg.paths.rejected_dir) / pending_path.name
    assert rejected_path.exists()

    # DB row points at new location and reason is set.
    row = repo.conn.execute(
        "SELECT status, output_path, rejection_reason FROM clips WHERE clip_id=?",
        ("v1_30_60",),
    ).fetchone()
    assert row["status"] == "rejected_quality"
    assert row["output_path"] == str(rejected_path)
    assert "density:" in row["rejection_reason"]


def test_relocate_failure_db_still_flips_with_pending_path(monkeypatch, tmp_path):
    """If os.replace raises, status STILL flips to rejected_quality but
    output_path keeps pointing at output/pending/. Recovery is manual."""
    cfg, repo, pending_path = _setup(tmp_path)
    _rig_for_failure(monkeypatch)

    def fake_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(runner_mod.os, "replace", fake_replace)

    res = screen_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert res.outcome == QualityOutcome.rejected_quality
    # File still at pending path because move failed.
    assert pending_path.exists()
    row = repo.conn.execute(
        "SELECT status, output_path, rejection_reason FROM clips WHERE clip_id=?",
        ("v1_30_60",),
    ).fetchone()
    assert row["status"] == "rejected_quality"
    assert row["output_path"] == str(pending_path)
    # Reason carries the original failures plus a 'move_failed' suffix in result.
    assert "density:" in row["rejection_reason"]
    assert res.reason and "move_failed" in res.reason


def test_dry_run_does_not_move_or_write(monkeypatch, tmp_path):
    cfg, repo, pending_path = _setup(tmp_path)
    _rig_for_failure(monkeypatch)

    res = screen_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", dry_run=True)
    assert res.outcome == QualityOutcome.rejected_quality
    # Filesystem unchanged.
    assert pending_path.exists()
    rejected_path = Path(cfg.paths.rejected_dir) / pending_path.name
    assert not rejected_path.exists()
    # DB unchanged.
    row = repo.conn.execute(
        "SELECT status, output_path FROM clips WHERE clip_id=?",
        ("v1_30_60",),
    ).fetchone()
    assert row["status"] == "rendered"
    assert row["output_path"] == str(pending_path)
