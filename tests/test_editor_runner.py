"""End-to-end editor orchestration tests (Pivot.3 — full-screen blurred-bg).

ffmpeg subprocess is monkeypatched. has_audio_stream is also patched so the
synthetic raw mp4 (just bytes) is treated as having audio.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.editor import ffmpeg_runner, runner as runner_mod
from src.editor.runner import EditorOutcome, render_one_clip, run_all
from src.state import Repository, connect, initialize_schema

from tests.conftest import StubConfig


# ---- fixtures ---------------------------------------------------------------


def _setup(tmp_path, *, music_enabled: bool = True, music_files: list[str] | None = None):
    """Build a StubConfig + clip + transcript + raw mp4 ready for render.

    music_files: optional list of basenames to seed in cfg.paths.music_dir.
    """
    cfg = StubConfig(tmp_path, music_enabled=music_enabled)

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

    # seed source mp4 (synthetic bytes; has_audio_stream is patched per test)
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

    # Optional music seed
    if music_files:
        music_dir = Path(cfg.paths.music_dir)
        for name in music_files:
            (music_dir / name).write_bytes(b"\x00" * 1024)

    # seed clip at policy_pass (editor's input filter)
    repo.upsert_selector_clip(
        clip_id="v1_30_60", video_id="v1",
        start_s=30.0, end_s=60.0,
        hook="h", suggested_title="Cool Hook Title",
        selection_method="heatmap_aided",
    )
    repo.set_clip_status("v1_30_60", "policy_pass")
    return cfg, repo


def _patch_audio_probe(monkeypatch, has_audio: bool = True):
    monkeypatch.setattr(ffmpeg_runner, "has_audio_stream", lambda p: has_audio)


def _patch_run_ffmpeg(monkeypatch, *, returncode=0, write_output=True):
    """Patch ffmpeg_runner.run_ffmpeg to fake a CompletedProcess and optionally
    write a tiny placeholder file at the output path so the size check passes."""
    def fake(argv, output_tmp_path):
        if write_output and returncode == 0:
            output_tmp_path.parent.mkdir(parents=True, exist_ok=True)
            output_tmp_path.write_bytes(b"fake mp4 bytes")
        size = output_tmp_path.stat().st_size if output_tmp_path.exists() else 0
        return ffmpeg_runner.FfmpegResult(
            returncode=returncode, stdout="",
            stderr="" if returncode == 0 else "fake error",
            output_size_bytes=size,
        )
    monkeypatch.setattr(runner_mod.ffmpeg_runner, "run_ffmpeg", fake)


# ---- success path -----------------------------------------------------------


def test_render_success_flips_status_no_gameplay_state(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path, music_files=["a.mp3"])
    _patch_audio_probe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.rendered

    row = repo.conn.execute("SELECT * FROM clips WHERE clip_id='v1_30_60'").fetchone()
    assert row["status"] == "rendered"
    assert row["title_slug"] is not None
    assert row["output_path"] is not None
    assert row["output_path"].endswith(".mp4")
    # downstream fields preserved (NULL since fresh)
    assert row["publish_at_utc"] is None
    # music track recorded in result
    assert r.music_track is not None
    assert r.music_track.endswith("a.mp3")


def test_render_success_with_no_music_pool_falls_back(tmp_path, monkeypatch):
    """Empty data/music/ → no music_track on result; render still succeeds."""
    cfg, repo = _setup(tmp_path, music_files=[])
    _patch_audio_probe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.rendered
    assert r.music_track is None


def test_render_success_with_music_disabled(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path, music_enabled=False, music_files=["a.mp3"])
    _patch_audio_probe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.rendered
    assert r.music_track is None


# ---- preflight matrix -------------------------------------------------------


def test_status_other_than_policy_pass_or_rendered_skipped(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    repo.set_clip_status("v1_30_60", "rejected_policy", reason="banned word")
    _patch_audio_probe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.skipped_wrong_status


def test_selected_status_skipped(tmp_path, monkeypatch):
    """Phase 4.5 regression: status='selected' is no longer editor-eligible."""
    cfg, repo = _setup(tmp_path)
    repo.set_clip_status("v1_30_60", "selected")
    _patch_audio_probe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.skipped_wrong_status


def test_already_rendered_no_force_skips(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    repo.set_clip_status("v1_30_60", "rendered", output_path="output/pending/x.mp4", title_slug="x")
    _patch_audio_probe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.skipped_already_rendered


def test_force_re_renders_unscheduled(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    repo.set_clip_status("v1_30_60", "rendered", output_path="output/pending/x.mp4", title_slug="x")
    _patch_audio_probe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", force=True)
    assert r.outcome == EditorOutcome.rendered


def test_force_blocked_for_scheduled_clip(tmp_path, monkeypatch):
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
    _patch_audio_probe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.rejected_render
    row = repo.conn.execute("SELECT status, rejection_reason FROM clips WHERE clip_id='v1_30_60'").fetchone()
    assert row["status"] == "rejected_render"
    assert row["rejection_reason"] == "source_missing"


def test_no_audio_stream_marks_rejected_render(tmp_path, monkeypatch):
    """Pivot.3: pre-render audio probe rejects clips with no audio."""
    cfg, repo = _setup(tmp_path)
    _patch_audio_probe(monkeypatch, has_audio=False)
    _patch_run_ffmpeg(monkeypatch)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.rejected_render
    assert r.reason == "no_audio_stream"
    row = repo.conn.execute("SELECT status, rejection_reason FROM clips WHERE clip_id='v1_30_60'").fetchone()
    assert row["status"] == "rejected_render"
    assert row["rejection_reason"] == "no_audio_stream"


def test_missing_transcript_does_not_advance(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    Path(cfg.paths.transcripts_dir, "v1.json").unlink()
    _patch_audio_probe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.error_no_transcript
    row = repo.conn.execute("SELECT status FROM clips WHERE clip_id='v1_30_60'").fetchone()
    assert row["status"] == "policy_pass"  # unchanged


def test_ffmpeg_failure_leaves_status_at_policy_pass(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    _patch_audio_probe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch, returncode=1, write_output=False)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.error_ffmpeg
    row = repo.conn.execute("SELECT status, output_path FROM clips WHERE clip_id='v1_30_60'").fetchone()
    assert row["status"] == "policy_pass"
    assert row["output_path"] is None


def test_zero_byte_output_treated_as_failure(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    _patch_audio_probe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch, returncode=0, write_output=False)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60")
    assert r.outcome == EditorOutcome.error_ffmpeg
    row = repo.conn.execute("SELECT status FROM clips WHERE clip_id='v1_30_60'").fetchone()
    assert row["status"] == "policy_pass"


# ---- dry-run ---------------------------------------------------------------


def test_dry_run_no_subprocess_no_db_writes(tmp_path, monkeypatch, capsys):
    cfg, repo = _setup(tmp_path, music_files=["a.mp3"])
    _patch_audio_probe(monkeypatch)

    def tripwire(*a, **kw):
        raise AssertionError("subprocess must NOT run in --dry-run")
    monkeypatch.setattr(runner_mod.ffmpeg_runner, "run_ffmpeg", tripwire)

    r = render_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", dry_run=True)
    assert r.outcome == EditorOutcome.rendered
    assert r.output_path is not None

    row = repo.conn.execute("SELECT status, output_path FROM clips WHERE clip_id='v1_30_60'").fetchone()
    assert row["status"] == "policy_pass"
    assert row["output_path"] is None
    assert not Path(r.output_path).exists()

    captured = capsys.readouterr()
    assert "[DRY-RUN] argv" in captured.out
    assert "h264_nvenc" in captured.out


# ---- run_all ---------------------------------------------------------------


def test_run_all_renders_only_policy_pass(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    repo.upsert_selector_clip(
        clip_id="v1_120_150", video_id="v1",
        start_s=120.0, end_s=150.0,
        hook="h2", suggested_title="Other",
        selection_method="transcript_only",
    )
    repo.set_clip_status("v1_120_150", "rejected_policy", reason="banned")

    _patch_audio_probe(monkeypatch)
    _patch_run_ffmpeg(monkeypatch)

    results = run_all(repo, cfg)
    assert len(results) == 1
    assert results[0].clip_id == "v1_30_60"
    assert results[0].outcome == EditorOutcome.rendered


def test_run_all_empty_returns_empty(tmp_path):
    cfg = StubConfig(tmp_path)
    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn); repo = Repository(conn)
    results = run_all(repo, cfg)
    assert results == []


def test_run_all_no_audio_alert_emitted(tmp_path, monkeypatch):
    """run_all writes editor_no_audio_stream alert when a clip has no audio."""
    cfg, repo = _setup(tmp_path)
    _patch_audio_probe(monkeypatch, has_audio=False)
    _patch_run_ffmpeg(monkeypatch)

    run_all(repo, cfg)
    alerts_md = (Path(cfg.paths.logs_dir) / "alerts.md").read_text()
    assert "editor_no_audio_stream" in alerts_md
