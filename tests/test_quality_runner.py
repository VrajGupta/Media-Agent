"""quality_screen runner: preflight, all-pass, multi-fail, batch alerts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.quality_screen import (
    confidence as confidence_mod,
    dedup as dedup_mod,
    density as density_mod,
    duration as duration_mod_,
    loudness as loudness_mod,
    runner as runner_mod,
)
from src.quality_screen.runner import QualityOutcome, run_all, screen_one_clip
from src.state import Repository, connect, initialize_schema
from tests.conftest import StubConfig


def _setup(tmp_path, *, words_in_window: int = 60):
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
    # Plenty of words across [30, 60] s — high density and high confidence.
    words = []
    for i in range(words_in_window):
        t = 30.0 + (i * (30.0 / max(words_in_window, 1)))
        words.append({"start": t, "end": t + 0.4, "word": f"w{i}", "probability": 0.95})
    payload = {
        "schema_version": 1, "video_id": "v1",
        "model": "large-v3", "compute_type": "int8_float16",
        "duration_seconds": 600.0, "language": "en", "language_probability": 0.99,
        "segments": [{"start": 30.0, "end": 60.0, "text": "x", "words": words}],
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


def _patch_pass_path(monkeypatch, *, duration_s=33.6, input_i=-14.0, phashes=None):
    """Wire all probes for a passing screen."""
    monkeypatch.setattr(duration_mod_, "probe_duration", lambda p: duration_s)
    monkeypatch.setattr(loudness_mod, "measure_loudness",
                        lambda p: loudness_mod.LoudnessMeasurement(input_i=input_i))
    if phashes is None:
        phashes = ["abcdef0123456789", "fedcba9876543210"]
    monkeypatch.setattr(
        dedup_mod, "compute_signals",
        lambda p, d: dedup_mod.DedupSignals(phashes=phashes, audio_fp="FAKEFP"),
    )


# ---- preflight matrix -------------------------------------------------------


def test_rendered_clip_is_screened(monkeypatch, tmp_path):
    cfg, repo, pending_path = _setup(tmp_path)
    _patch_pass_path(monkeypatch)
    res = screen_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert res.outcome == QualityOutcome.quality_pass
    row = repo.conn.execute(
        "SELECT status FROM clips WHERE clip_id=?", ("v1_30_60",)
    ).fetchone()
    assert row["status"] == "quality_pass"


def test_already_quality_pass_skips_without_force(tmp_path):
    cfg, repo, _ = _setup(tmp_path)
    repo.conn.execute(
        "UPDATE clips SET status='quality_pass' WHERE clip_id=?", ("v1_30_60",),
    )
    res = screen_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert res.outcome == QualityOutcome.skipped_already_screened


def test_scheduled_clip_is_locked(tmp_path):
    cfg, repo, _ = _setup(tmp_path)
    repo.conn.execute(
        "UPDATE clips SET publish_at_utc='2026-05-01T09:00:00Z' WHERE clip_id=?",
        ("v1_30_60",),
    )
    res = screen_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", force=True)
    assert res.outcome == QualityOutcome.skipped_locked


def test_uploaded_clip_is_locked(tmp_path):
    cfg, repo, _ = _setup(tmp_path)
    repo.conn.execute(
        "UPDATE clips SET youtube_video_id='abc' WHERE clip_id=?", ("v1_30_60",),
    )
    res = screen_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", force=True)
    assert res.outcome == QualityOutcome.skipped_locked


# ---- foundational probe failure --------------------------------------------


def test_probe_failure_returns_error_probe_and_aborts(monkeypatch, tmp_path):
    cfg, repo, _ = _setup(tmp_path)
    monkeypatch.setattr(duration_mod_, "probe_duration", lambda p: None)
    # Other checks should NEVER be invoked when probe fails.
    monkeypatch.setattr(loudness_mod, "measure_loudness",
                        lambda p: pytest.fail("loudness should not run"))
    monkeypatch.setattr(dedup_mod, "compute_signals",
                        lambda p, d: pytest.fail("dedup should not run"))

    res = screen_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert res.outcome == QualityOutcome.error_probe
    row = repo.conn.execute(
        "SELECT status FROM clips WHERE clip_id=?", ("v1_30_60",)
    ).fetchone()
    assert row["status"] == "rendered"  # unchanged


def test_missing_output_returns_error_no_output(tmp_path):
    cfg, repo, pending_path = _setup(tmp_path)
    pending_path.unlink()
    res = screen_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert res.outcome == QualityOutcome.error_no_output


# ---- happy path inserts dup_hashes -----------------------------------------


def test_pass_inserts_dup_hashes_atomically(monkeypatch, tmp_path):
    cfg, repo, _ = _setup(tmp_path)
    _patch_pass_path(
        monkeypatch,
        phashes=["abcdef0123456789", "fedcba9876543210", "1111222233334444"],
    )
    res = screen_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert res.outcome == QualityOutcome.quality_pass

    rows = repo.conn.execute(
        "SELECT phash, audio_fp FROM dup_hashes WHERE clip_id=? ORDER BY phash",
        ("v1_30_60",),
    ).fetchall()
    assert len(rows) == 3
    assert all(r["audio_fp"] == "FAKEFP" for r in rows)


def test_dry_run_does_not_insert_dup_hashes(monkeypatch, tmp_path):
    cfg, repo, _ = _setup(tmp_path)
    _patch_pass_path(monkeypatch)
    res = screen_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", dry_run=True)
    assert res.outcome == QualityOutcome.quality_pass
    rows = repo.conn.execute(
        "SELECT * FROM dup_hashes WHERE clip_id=?", ("v1_30_60",),
    ).fetchall()
    assert rows == []
    row = repo.conn.execute(
        "SELECT status FROM clips WHERE clip_id=?", ("v1_30_60",)
    ).fetchone()
    assert row["status"] == "rendered"


# ---- multi-fail aggregation ------------------------------------------------


def test_multiple_failures_concatenated_with_semicolons(monkeypatch, tmp_path):
    """Wire duration AND density to fail simultaneously."""
    cfg, repo, _ = _setup(tmp_path, words_in_window=2)  # very low density
    monkeypatch.setattr(duration_mod_, "probe_duration", lambda p: 18.0)  # under 25
    monkeypatch.setattr(loudness_mod, "measure_loudness",
                        lambda p: loudness_mod.LoudnessMeasurement(input_i=-14.0))
    monkeypatch.setattr(
        dedup_mod, "compute_signals",
        lambda p, d: dedup_mod.DedupSignals(phashes=["abcdef0123456789"], audio_fp=None),
    )
    res = screen_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert res.outcome == QualityOutcome.rejected_quality
    assert res.reason is not None
    # Both checks must appear in the joined reason.
    assert "duration:" in res.reason
    assert "density:" in res.reason
    assert ";" in res.reason


def test_loudness_warn_band_passes_with_alert(monkeypatch, tmp_path):
    cfg, repo, _ = _setup(tmp_path)
    monkeypatch.setattr(duration_mod_, "probe_duration", lambda p: 33.6)
    monkeypatch.setattr(loudness_mod, "measure_loudness",
                        lambda p: loudness_mod.LoudnessMeasurement(input_i=-15.2))
    monkeypatch.setattr(
        dedup_mod, "compute_signals",
        lambda p, d: dedup_mod.DedupSignals(phashes=["abcdef0123456789"], audio_fp=None),
    )
    res = screen_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert res.outcome == QualityOutcome.quality_pass
    assert res.loudness_band == "warn"


def test_loudness_reject_band_fails(monkeypatch, tmp_path):
    cfg, repo, _ = _setup(tmp_path)
    monkeypatch.setattr(duration_mod_, "probe_duration", lambda p: 33.6)
    monkeypatch.setattr(loudness_mod, "measure_loudness",
                        lambda p: loudness_mod.LoudnessMeasurement(input_i=-10.0))
    monkeypatch.setattr(
        dedup_mod, "compute_signals",
        lambda p, d: dedup_mod.DedupSignals(phashes=["abcdef0123456789"], audio_fp=None),
    )
    res = screen_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert res.outcome == QualityOutcome.rejected_quality
    assert "loudness:" in (res.reason or "")


# ---- run_all ---------------------------------------------------------------


def test_run_all_filters_to_rendered_and_unscheduled(monkeypatch, tmp_path):
    cfg, repo, _ = _setup(tmp_path)
    _patch_pass_path(monkeypatch)
    # Add a second clip already at quality_pass — must be filtered out.
    repo.upsert_selector_clip(
        clip_id="v1_60_90", video_id="v1",
        start_s=60.0, end_s=90.0,
        hook="h", suggested_title="Other",
        selection_method="transcript_only",
    )
    repo.set_clip_status("v1_60_90", "quality_pass")

    results = run_all(repo, cfg)
    ids = [r.clip_id for r in results]
    assert ids == ["v1_30_60"]


def test_run_all_emits_loudness_warn_alert(monkeypatch, tmp_path):
    cfg, repo, _ = _setup(tmp_path)
    monkeypatch.setattr(duration_mod_, "probe_duration", lambda p: 33.6)
    monkeypatch.setattr(loudness_mod, "measure_loudness",
                        lambda p: loudness_mod.LoudnessMeasurement(input_i=-15.2))
    monkeypatch.setattr(
        dedup_mod, "compute_signals",
        lambda p, d: dedup_mod.DedupSignals(phashes=["abcdef0123456789"], audio_fp=None),
    )
    run_all(repo, cfg)

    alerts_path = Path(cfg.paths.logs_dir) / "alerts.md"
    body = alerts_path.read_text(encoding="utf-8")
    assert "loudness_warn" in body
