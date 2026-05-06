"""reconcile_approvals tests — the human-review gate."""

from __future__ import annotations

from pathlib import Path

from src.daily_upload import reconcile_approvals
from src.state import Repository, connect, initialize_schema

from tests.conftest import StubConfig


def _new_repo(tmp_path) -> Repository:
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _seed_video(repo: Repository) -> None:
    repo.conn.execute(
        "INSERT INTO videos (video_id, title, channel, duration_seconds, views, "
        "published_at, keyword, virality_score, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("v1", "t", "c", 600, 1, "2026-04-01T00:00:00Z", "movies", 1.0, "downloaded"),
    )


def _seed_clip(
    repo: Repository,
    *,
    clip_id: str = "v1_30_60",
    status: str = "quality_pass",
    publish_at_utc: str | None = "2026-05-03T01:00:00Z",
    output_path: str | None = None,
    youtube_video_id: str | None = None,
    suggested_title: str = "great hook",
) -> None:
    repo.conn.execute(
        "INSERT INTO clips (clip_id, video_id, start_s, end_s, hook, suggested_title, "
        "selection_method, status, publish_at_utc, output_path, youtube_video_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (clip_id, "v1", 30.0, 60.0, "hook", suggested_title, "transcript_only",
         status, publish_at_utc, output_path, youtube_video_id),
    )


def test_flips_quality_pass_when_basename_matches_in_approved(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    pending = Path(cfg.paths.pending_dir)
    approved = Path(cfg.paths.approved_dir)
    _seed_video(repo)
    pending_file = pending / "2026-05-03__slot_0900__great_hook_abcd.mp4"
    pending_file.write_bytes(b"x")
    _seed_clip(repo, output_path=str(pending_file))

    # User drags the file to approved/.
    approved_file = approved / pending_file.name
    approved_file.write_bytes(b"x")

    flipped = reconcile_approvals(repo, cfg)
    assert flipped == ["v1_30_60"]
    row = repo.conn.execute(
        "SELECT status, output_path FROM clips WHERE clip_id=?", ("v1_30_60",)
    ).fetchone()
    assert row["status"] == "approved"
    assert row["output_path"] == str(approved_file)


def test_does_not_flip_when_no_file_in_approved(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    pending = Path(cfg.paths.pending_dir)
    _seed_video(repo)
    pending_file = pending / "2026-05-03__slot_0900__great_hook_abcd.mp4"
    pending_file.write_bytes(b"x")
    _seed_clip(repo, output_path=str(pending_file))

    flipped = reconcile_approvals(repo, cfg)
    assert flipped == []
    row = repo.conn.execute(
        "SELECT status FROM clips WHERE clip_id=?", ("v1_30_60",)
    ).fetchone()
    assert row["status"] == "quality_pass"


def test_idempotent_on_already_approved(tmp_path):
    """Running twice in a row → second run is a no-op."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    pending = Path(cfg.paths.pending_dir)
    approved = Path(cfg.paths.approved_dir)
    _seed_video(repo)
    pending_file = pending / "2026-05-03__slot_0900__slug_abcd.mp4"
    pending_file.write_bytes(b"x")
    _seed_clip(repo, output_path=str(pending_file))
    approved_file = approved / pending_file.name
    approved_file.write_bytes(b"x")

    flipped1 = reconcile_approvals(repo, cfg)
    flipped2 = reconcile_approvals(repo, cfg)
    assert flipped1 == ["v1_30_60"]
    assert flipped2 == []   # second pass: nothing in quality_pass to flip


def test_slug_with_underscores_does_not_break_matching(tmp_path):
    """Title slugs can contain `_` heavily; basename equality must work."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    pending = Path(cfg.paths.pending_dir)
    approved = Path(cfg.paths.approved_dir)
    _seed_video(repo)
    weird_basename = "2026-05-03__slot_0900__a_b_c_d_e_f_g_xxxx.mp4"
    pending_file = pending / weird_basename
    pending_file.write_bytes(b"x")
    _seed_clip(repo, output_path=str(pending_file))
    approved_file = approved / weird_basename
    approved_file.write_bytes(b"x")

    flipped = reconcile_approvals(repo, cfg)
    assert flipped == ["v1_30_60"]


def test_ignores_non_mp4_files(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    approved = Path(cfg.paths.approved_dir)
    _seed_video(repo)
    pending_file = Path(cfg.paths.pending_dir) / "x.mp4"
    pending_file.write_bytes(b"x")
    _seed_clip(repo, output_path=str(pending_file))
    # Non-mp4 file in approved/.
    (approved / "x.txt").write_text("not a clip")
    (approved / ".hidden").write_text("dotfile")

    flipped = reconcile_approvals(repo, cfg)
    assert flipped == []


def test_ignores_clips_with_publish_at_utc_null(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    pending = Path(cfg.paths.pending_dir)
    approved = Path(cfg.paths.approved_dir)
    _seed_video(repo)
    pending_file = pending / "anyfile.mp4"
    pending_file.write_bytes(b"x")
    _seed_clip(repo, publish_at_utc=None, output_path=str(pending_file))
    (approved / "anyfile.mp4").write_bytes(b"x")

    flipped = reconcile_approvals(repo, cfg)
    assert flipped == []


def test_dry_run_logs_but_does_not_write(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    pending = Path(cfg.paths.pending_dir)
    approved = Path(cfg.paths.approved_dir)
    _seed_video(repo)
    pending_file = pending / "x.mp4"
    pending_file.write_bytes(b"x")
    _seed_clip(repo, output_path=str(pending_file))
    (approved / "x.mp4").write_bytes(b"x")

    flipped = reconcile_approvals(repo, cfg, dry_run=True)
    assert flipped == ["v1_30_60"]
    row = repo.conn.execute(
        "SELECT status FROM clips WHERE clip_id=?", ("v1_30_60",)
    ).fetchone()
    assert row["status"] == "quality_pass"   # NOT flipped under dry-run
