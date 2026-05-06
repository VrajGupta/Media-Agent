"""Today-window math + clips_for_upload_due tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.daily_upload import _compute_today_window_end
from src.state import Repository, connect, initialize_schema

from tests.conftest import StubConfig


SGT = ZoneInfo("Asia/Singapore")


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
    clip_id: str,
    status: str = "quality_pass",
    publish_at_utc: str | None = None,
    youtube_video_id: str | None = None,
) -> None:
    repo.conn.execute(
        "INSERT INTO clips (clip_id, video_id, start_s, end_s, hook, suggested_title, "
        "selection_method, status, publish_at_utc, youtube_video_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (clip_id, "v1", 30.0, 60.0, "hook", "title", "transcript_only",
         status, publish_at_utc, youtube_video_id),
    )


def test_window_end_in_sgt_is_2359_local(tmp_path):
    cfg = StubConfig(tmp_path)
    # Pass a UTC instant; expect end-of-today in SGT converted back to UTC.
    # 2026-05-03 04:00 UTC = 2026-05-03 12:00 SGT → end-of-today SGT = 2026-05-03 23:59 SGT
    # 2026-05-03 23:59 SGT = 2026-05-03 15:59:00Z
    now_utc = datetime(2026, 5, 3, 4, 0, tzinfo=timezone.utc)
    end_iso = _compute_today_window_end(cfg, now=now_utc)
    assert end_iso == "2026-05-03T15:59:59Z"


def test_window_end_handles_local_day_boundary(tmp_path):
    cfg = StubConfig(tmp_path)
    # 2026-05-03 16:00 UTC → 2026-05-04 00:00 SGT (already next local day).
    # End-of-today in SGT = 2026-05-04 23:59 SGT = 2026-05-04 15:59 UTC.
    now_utc = datetime(2026, 5, 3, 16, 0, tzinfo=timezone.utc)
    end_iso = _compute_today_window_end(cfg, now=now_utc)
    assert end_iso == "2026-05-04T15:59:59Z"


def test_clips_for_upload_due_filters_by_window(tmp_path):
    repo = _new_repo(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, clip_id="early",  publish_at_utc="2026-05-01T12:00:00Z")
    _seed_clip(repo, clip_id="middle", publish_at_utc="2026-05-03T12:00:00Z")
    _seed_clip(repo, clip_id="late",   publish_at_utc="2026-05-05T12:00:00Z")

    rows = repo.clips_for_upload_due("2026-05-03T15:59:59Z")
    ids = [r["clip_id"] for r in rows]
    assert ids == ["early", "middle"]


def test_clips_for_upload_due_status_whitelist_approved_only(tmp_path):
    """human_review=True path: only `approved` clips are returned."""
    repo = _new_repo(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, clip_id="qpc", status="quality_pass",
               publish_at_utc="2026-05-03T01:00:00Z")
    _seed_clip(repo, clip_id="apc", status="approved",
               publish_at_utc="2026-05-03T02:00:00Z")

    rows = repo.clips_for_upload_due(
        "2026-05-03T15:59:59Z", statuses=("approved",)
    )
    assert [r["clip_id"] for r in rows] == ["apc"]


def test_clips_for_upload_due_status_whitelist_both(tmp_path):
    """human_review=False path: both quality_pass + approved returned."""
    repo = _new_repo(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, clip_id="qpc", status="quality_pass",
               publish_at_utc="2026-05-03T01:00:00Z")
    _seed_clip(repo, clip_id="apc", status="approved",
               publish_at_utc="2026-05-03T02:00:00Z")

    rows = repo.clips_for_upload_due(
        "2026-05-03T15:59:59Z", statuses=("quality_pass", "approved"),
    )
    # publish_at_utc ASC → qpc (01:00) before apc (02:00).
    assert [r["clip_id"] for r in rows] == ["qpc", "apc"]


def test_clips_for_upload_due_excludes_uploaded(tmp_path):
    repo = _new_repo(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, clip_id="x", status="approved",
               publish_at_utc="2026-05-03T01:00:00Z",
               youtube_video_id="ytX")
    rows = repo.clips_for_upload_due(
        "2026-05-03T15:59:59Z", statuses=("approved",),
    )
    assert rows == []


def test_clips_for_upload_due_includes_past_due_clips(tmp_path):
    """Missed-slot recovery requires past-due clips to come back through."""
    repo = _new_repo(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, clip_id="ancient", status="approved",
               publish_at_utc="2024-01-01T00:00:00Z")   # very past
    rows = repo.clips_for_upload_due(
        "2026-05-03T15:59:59Z", statuses=("approved",),
    )
    assert [r["clip_id"] for r in rows] == ["ancient"]


def test_clips_for_upload_due_empty_statuses_returns_empty(tmp_path):
    repo = _new_repo(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, clip_id="x", status="approved",
               publish_at_utc="2026-05-03T01:00:00Z")
    rows = repo.clips_for_upload_due("2026-05-03T15:59:59Z", statuses=())
    assert rows == []
