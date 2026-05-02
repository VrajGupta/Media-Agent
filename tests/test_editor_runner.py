"""End-to-end editor orchestration tests. ffmpeg subprocess monkeypatched.

Mirrors tests/test_selector_runner.py: replaces ffmpeg_runner.run_ffmpeg
with a stub that fakes a CompletedProcess and optionally writes a tiny
placeholder file at the output path so the size check sees something.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.editor import ffmpeg_runner, runner as runner_mod
from src.editor.runner import EditorOutcome, run_all, render_one_clip
from src.state import Repository, connect, initialize_schema
from tests.conftest import StubConfig


# ---- fixtures ---------------------------------------------------------------


def _setup(tmp_path):
    """Build a StubConfig with one source mp4, one transcript, one gameplay file."""
    pool_dir = tmp_path / "data" / "gameplay"
    pool_dir.mkdir(parents=True)
    gameplay_file = pool_dir / "subway.mp4"
    gameplay_file.write_bytes(b"\x00" * 1024)

    cfg = StubConfig(tmp_path, gameplay_pool=[str(gameplay_file)])

    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn); repo = Repository(conn)

    # seed video
    repo.discovery_upsert_video(
        video_id="v1", title="T", channel="C",
        duration_seconds=600, views=100, likes=1, comments=1,
        published_at="2026-04-01T00:00:00Z",
        keyword="k", virality_score=1.5,
    )
    repo.set_video_status("v1", "selected")

    # seed source mp4
    raw = Path(cfg.paths.raw_dir) / "v1.mp4"
    raw.write_bytes(b"\x00" * 4096)

    # seed transcript with word-level data
    transcripts = Path(cfg.paths.transcripts_dir)
    payload = {
        "schema_version": 1, "video_id": "v1",
        "model": "large-v3", "compute_type": "int8_float16",
        "duration_seconds": 600.0, "language": "en", "language_probability": 0.99,
        "segments": [
            {"start": 30.0, "end": 35.0, "text": "hello world",
             "words": [
                 {"start": 30.0, "end": 31.0, "word": "hello", "probability": 0.9},
                 {"start": 31.0, "end": 32.0, "word": "world", "probability": 0.9},
             ]}
        ],
    }
    (transcripts / "v1.json").write_text(json.dumps(payload), encoding="utf-8")

    # seed clip
    repo.upsert_selector_clip(
        clip_id="v1_30_60", video_id="v1",
        start_s=30.0, end_s=60.0,
        hook="h", suggested_title="Cool Hook Title",
        selection_method="heatmap_aided",
    )
    # Phase 4.5: advance clip past the policy_gate. Editor reads
    # status='policy_pass' as its input now (selected clips wait for the gate).
    repo.set_clip_status("v1_30_60", "policy_pass")
    return cfg, repo


def _patch_ffprobe(monkeypatch, duration=600.0):
    monkeypatch.setattr(ffmpeg_runner, "ffprobe_duration_seconds", lambda p: duration)


def _patch_run_ffmpeg(monkeypatch, *, returncode=0, write_output=True):
    """Patch ffmpeg_runner.run_ffmpeg. Optionally writes a fake mp4 byte at the
    tmp output path so the size check passes."""
    def fake(argv, output_tmp_path):
        if write_output and returncode == 0:
            output_tmp_path.parent.mkdir(parents=True, exist_ok=True)
            output_tmp_path.write_bytes(b"fake mp4 bytes")  # nonzero size
        size = output_tmp_path.stat().st_size if output_tmp_path.exists() else 0
        return ffmpeg_runner.FfmpegResult(
            returncode=returncode, stdout="", stderr="" if returncode == 0 else "fake error",
            output_size_bytes=size,
        )

    monkeypatch.setattr(runner_mod.ffmpeg_runner, "run_ffmpeg", fake)


# ---- success path -----------------------------------------------------------


def test_render_success_flips_status_and_advances_gameplay(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    _patch_ffprobe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.rendered

    # clip row updated
    row = repo.conn.execute("SELECT * FROM clips WHERE clip_id='v1_30_60'").fetchone()
    assert row["status"] == "rendered"
    assert row["title_slug"] is not None
    assert row["output_path"] is not None
    assert row["output_path"].endswith(".mp4")
    # downstream fields preserved (NULL since fresh)
    assert row["publish_at_utc"] is None

    # gameplay state advanced
    assert repo.read_gameplay_pointer() == 0  # one file, wraps back to 0
    last_offset, file_dur = repo.read_gameplay_cursor(cfg.gameplay_pool[0])
    assert last_offset == 30.0  # advanced by clip duration
    assert file_dur == 600.0


# ---- preflight matrix -------------------------------------------------------


def test_status_other_than_policy_pass_or_rendered_skipped(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    repo.set_clip_status("v1_30_60", "rejected_policy", reason="banned word")
    _patch_ffprobe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.skipped_wrong_status


def test_selected_status_now_skipped_after_phase_4_5(tmp_path, monkeypatch):
    """Phase 4.5 regression: status='selected' is no longer editor-eligible.

    The clip must have been advanced to 'policy_pass' by policy_gate first."""
    cfg, repo = _setup(tmp_path)
    repo.set_clip_status("v1_30_60", "selected")
    _patch_ffprobe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.skipped_wrong_status


def test_already_rendered_no_force_skips(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    repo.set_clip_status("v1_30_60", "rendered", output_path="output/pending/x.mp4", title_slug="x")
    _patch_ffprobe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.skipped_already_rendered


def test_force_re_renders_unscheduled(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    repo.set_clip_status("v1_30_60", "rendered", output_path="output/pending/x.mp4", title_slug="x")
    _patch_ffprobe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", force=True)
    assert r.outcome == EditorOutcome.rendered


def test_force_blocked_for_scheduled_clip(tmp_path, monkeypatch):
    """--force is gated: don't re-render clips that have been scheduled."""
    cfg, repo = _setup(tmp_path)
    repo.conn.execute(
        "UPDATE clips SET status='rendered', publish_at_utc='2026-05-15T09:00:00Z',"
        " output_path='output/pending/x.mp4', title_slug='x' WHERE clip_id='v1_30_60'"
    )

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", force=True)
    assert r.outcome == EditorOutcome.skipped_locked


def test_force_blocked_for_uploaded_clip(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    repo.conn.execute(
        "UPDATE clips SET status='rendered', youtube_video_id='ytid_abc',"
        " output_path='output/pending/x.mp4', title_slug='x' WHERE clip_id='v1_30_60'"
    )

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", force=True)
    assert r.outcome == EditorOutcome.skipped_locked


# ---- failure modes ----------------------------------------------------------


def test_source_missing_marks_rejected_render(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    Path(cfg.paths.raw_dir, "v1.mp4").unlink()
    _patch_ffprobe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.rejected_render
    row = repo.conn.execute("SELECT status, rejection_reason FROM clips WHERE clip_id='v1_30_60'").fetchone()
    assert row["status"] == "rejected_render"
    assert row["rejection_reason"] == "source_missing"


def test_missing_transcript_does_not_advance(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    Path(cfg.paths.transcripts_dir, "v1.json").unlink()
    _patch_ffprobe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.error_no_transcript
    row = repo.conn.execute("SELECT status FROM clips WHERE clip_id='v1_30_60'").fetchone()
    assert row["status"] == "policy_pass"  # unchanged


def test_ffmpeg_failure_leaves_status_at_policy_pass(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    _patch_ffprobe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch, returncode=1, write_output=False)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.error_ffmpeg
    row = repo.conn.execute("SELECT status, output_path FROM clips WHERE clip_id='v1_30_60'").fetchone()
    assert row["status"] == "policy_pass"
    assert row["output_path"] is None
    # gameplay pointer + cursor unchanged
    assert repo.read_gameplay_pointer() == 0
    last_offset, _ = repo.read_gameplay_cursor(cfg.gameplay_pool[0])
    assert last_offset == 0.0


def test_zero_byte_output_treated_as_failure(tmp_path, monkeypatch):
    """ffmpeg returns 0 but writes nothing -> treated as failure."""
    cfg, repo = _setup(tmp_path)
    _patch_ffprobe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch, returncode=0, write_output=False)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.error_ffmpeg
    row = repo.conn.execute("SELECT status FROM clips WHERE clip_id='v1_30_60'").fetchone()
    assert row["status"] == "policy_pass"


# ---- dry-run ---------------------------------------------------------------


def test_dry_run_no_subprocess_no_db_writes(tmp_path, monkeypatch, capsys):
    cfg, repo = _setup(tmp_path)
    _patch_ffprobe(monkeypatch)

    # Tripwire: any call to run_ffmpeg is a test failure.
    def tripwire(*a, **kw):
        raise AssertionError("subprocess must NOT run in --dry-run")
    monkeypatch.setattr(runner_mod.ffmpeg_runner, "run_ffmpeg", tripwire)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", dry_run=True)
    assert r.outcome == EditorOutcome.rendered  # logical "would-render"
    assert r.output_path is not None

    # No DB writes.
    row = repo.conn.execute("SELECT status, output_path FROM clips WHERE clip_id='v1_30_60'").fetchone()
    assert row["status"] == "policy_pass"
    assert row["output_path"] is None

    # No file written at the target path.
    assert not Path(r.output_path).exists()

    # argv printed to stdout.
    captured = capsys.readouterr()
    assert "[DRY-RUN] argv" in captured.out
    assert "h264_nvenc" in captured.out


# ---- run_all ---------------------------------------------------------------


def test_run_all_renders_only_policy_pass(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    # Add a second clip in a status that should be skipped.
    repo.upsert_selector_clip(
        clip_id="v1_120_150", video_id="v1",
        start_s=120.0, end_s=150.0,
        hook="h2", suggested_title="Other",
        selection_method="transcript_only",
    )
    repo.set_clip_status("v1_120_150", "rejected_policy", reason="banned")

    _patch_ffprobe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch)

    results = run_all(repo, cfg)
    assert len(results) == 1
    assert results[0].clip_id == "v1_30_60"
    assert results[0].outcome == EditorOutcome.rendered


def test_run_all_empty_returns_empty(tmp_path):
    cfg = StubConfig(tmp_path, gameplay_pool=[])
    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn); repo = Repository(conn)
    results = run_all(repo, cfg)
    assert results == []
