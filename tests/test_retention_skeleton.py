"""Phase 6 retention skeleton tests — threshold math + DB queries.

Real deletion is Phase 7. These tests validate the enumeration helpers.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.retention.cleanup import (
    count_dup_hashes_to_prune,
    count_quota_usage_to_prune,
    list_output_post_upload_candidates,
    list_raw_candidates,
    list_rejected_candidates,
    list_transcript_candidates,
    run_all,
)
from src.state import Repository, connect, initialize_schema

from tests.conftest import StubConfig


def _new_repo(tmp_path) -> Repository:
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _seed_video(repo: Repository, video_id: str = "v1") -> None:
    repo.conn.execute(
        "INSERT INTO videos (video_id, title, channel, duration_seconds, views, "
        "published_at, keyword, virality_score, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (video_id, "t", "c", 600, 1, "2026-04-01T00:00:00Z", "movies", 1.0, "downloaded"),
    )


def _seed_clip(
    repo: Repository,
    *,
    clip_id: str,
    video_id: str = "v1",
    status: str = "uploaded",
    output_path: str | None = None,
    updated_at: str | None = None,
) -> None:
    repo.conn.execute(
        "INSERT INTO clips (clip_id, video_id, start_s, end_s, hook, suggested_title, "
        "selection_method, status, output_path, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')))",
        (clip_id, video_id, 30.0, 60.0, "h", "t", "transcript_only",
         status, output_path, updated_at),
    )


def _set_mtime_days_ago(p: Path, days: float) -> None:
    """Backdate a file's mtime by `days` days."""
    target = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    os.utime(p, (target, target))


def test_raw_candidates_old_with_all_uploaded(tmp_path):
    """Raw mp4 older than 14 days AND all derived clips uploaded → candidate."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    raw_dir = Path(cfg.paths.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    f = raw_dir / "v1.mp4"
    f.write_bytes(b"x")
    _set_mtime_days_ago(f, 20)
    _seed_video(repo)
    _seed_clip(repo, clip_id="v1_30_60", status="uploaded")

    candidates = list_raw_candidates(repo, cfg)
    assert candidates == [str(f)]


def test_raw_candidates_excluded_when_clip_not_uploaded(tmp_path):
    """Raw mp4 older than 14 days BUT a derived clip is still rendered → no."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    raw_dir = Path(cfg.paths.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    f = raw_dir / "v1.mp4"
    f.write_bytes(b"x")
    _set_mtime_days_ago(f, 20)
    _seed_video(repo)
    _seed_clip(repo, clip_id="v1_30_60", status="rendered")

    candidates = list_raw_candidates(repo, cfg)
    assert candidates == []


def test_raw_candidates_excluded_when_too_recent(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    raw_dir = Path(cfg.paths.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    f = raw_dir / "v1.mp4"
    f.write_bytes(b"x")
    _set_mtime_days_ago(f, 5)   # only 5 days old
    _seed_video(repo)
    _seed_clip(repo, clip_id="v1_30_60", status="uploaded")

    candidates = list_raw_candidates(repo, cfg)
    assert candidates == []


def test_transcript_candidates_uses_mtime(tmp_path):
    cfg = StubConfig(tmp_path)
    transcripts = Path(cfg.paths.transcripts_dir)
    transcripts.mkdir(parents=True, exist_ok=True)
    old = transcripts / "old.json"
    new = transcripts / "new.json"
    old.write_text("{}")
    new.write_text("{}")
    _set_mtime_days_ago(old, 100)
    _set_mtime_days_ago(new, 30)

    candidates = list_transcript_candidates(cfg)
    assert candidates == [str(old)]


def test_dup_hashes_count_threshold(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, clip_id="c_old", status="uploaded")
    _seed_clip(repo, clip_id="c_new", status="uploaded")
    # Insert dup_hashes rows with explicit created_at.
    repo.conn.execute(
        "INSERT INTO dup_hashes (clip_id, phash, created_at) VALUES (?, ?, ?)",
        ("c_old", "deadbeef", "2025-01-01 00:00:00"),
    )
    repo.conn.execute(
        "INSERT INTO dup_hashes (clip_id, phash, created_at) VALUES (?, ?, ?)",
        ("c_new", "cafebabe", "2026-04-30 00:00:00"),
    )
    # now=2026-05-03 → 90-day cutoff = 2026-02-02. 2025-01-01 is past; 2026-04-30 isn't.
    n = count_dup_hashes_to_prune(repo, cfg, now=datetime(2026, 5, 3, tzinfo=timezone.utc))
    assert n == 1


def test_quota_usage_count_threshold(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    repo.conn.execute(
        "INSERT INTO quota_usage (date, endpoint, units) VALUES (?, ?, ?)",
        ("2025-01-01", "search.list", 100),
    )
    repo.conn.execute(
        "INSERT INTO quota_usage (date, endpoint, units) VALUES (?, ?, ?)",
        ("2026-04-30", "videos.insert", 1600),
    )
    n = count_quota_usage_to_prune(repo, cfg, now=datetime(2026, 5, 3, tzinfo=timezone.utc))
    assert n == 1


def test_run_all_dry_run_aggregates(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    result = run_all(repo, cfg, dry_run=True)
    assert result.dry_run is True
    assert result.would_delete_raw == []
    assert result.would_delete_transcripts == []
    assert result.would_prune_dup_hashes == 0


def test_run_all_real_mode_raises_in_phase6(tmp_path):
    """Phase 6 cleanly refuses real-mode deletion; Phase 7 will flip this."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    with pytest.raises(NotImplementedError):
        run_all(repo, cfg, dry_run=False)
