"""Phase 7 retention tests — threshold math + DB queries + real deletion.

Phase 6 shipped the enumeration helpers; Phase 7 added real-mode deletion,
DB pruning, and best-effort VACUUM.
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


# ---- Phase 7 real-mode deletion ---------------------------------------------


def test_run_all_real_mode_deletes_old_raw_with_uploaded_clips(tmp_path):
    """Old raw mp4 + all derived clips uploaded → real-mode deletes the file
    and counts it in deleted_raw."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    raw_dir = Path(cfg.paths.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    f = raw_dir / "v1.mp4"
    f.write_bytes(b"x")
    _set_mtime_days_ago(f, 20)
    _seed_video(repo)
    _seed_clip(repo, clip_id="v1_30_60", status="uploaded")

    result = run_all(repo, cfg, dry_run=False)
    assert result.dry_run is False
    assert result.deleted_raw == 1
    assert not f.exists()


def test_run_all_real_mode_preserves_in_progress_raw(tmp_path):
    """Old raw mp4 with one rendered clip → real-mode does NOT delete (guard)."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    raw_dir = Path(cfg.paths.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    f = raw_dir / "v1.mp4"
    f.write_bytes(b"x")
    _set_mtime_days_ago(f, 20)
    _seed_video(repo)
    _seed_clip(repo, clip_id="v1_30_60", status="rendered")

    result = run_all(repo, cfg, dry_run=False)
    assert result.deleted_raw == 0
    assert f.exists()  # untouched


def test_run_all_real_mode_prunes_dup_hashes(tmp_path):
    """Real-mode deletes dup_hashes rows older than 90 days; recent rows stay."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, clip_id="c_old", status="uploaded")
    _seed_clip(repo, clip_id="c_new", status="uploaded")
    repo.conn.execute(
        "INSERT INTO dup_hashes (clip_id, phash, created_at) VALUES (?, ?, ?)",
        ("c_old", "deadbeef", "2025-01-01 00:00:00"),
    )
    repo.conn.execute(
        "INSERT INTO dup_hashes (clip_id, phash, created_at) VALUES (?, ?, ?)",
        ("c_new", "cafebabe", "2026-04-30 00:00:00"),
    )

    now = datetime(2026, 5, 3, tzinfo=timezone.utc)
    result = run_all(repo, cfg, dry_run=False, now=now)
    assert result.pruned_dup_hashes == 1
    remaining = repo.conn.execute("SELECT phash FROM dup_hashes").fetchall()
    assert [r["phash"] for r in remaining] == ["cafebabe"]


def test_run_all_real_mode_prunes_quota_usage(tmp_path):
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
    now = datetime(2026, 5, 3, tzinfo=timezone.utc)
    result = run_all(repo, cfg, dry_run=False, now=now)
    assert result.pruned_quota_usage == 1
    remaining = repo.conn.execute("SELECT date FROM quota_usage").fetchall()
    assert [r["date"] for r in remaining] == ["2026-04-30"]


def test_run_all_real_mode_filenotfound_not_an_error(tmp_path, monkeypatch):
    """If a candidate file is gone by the time unlink runs, it's counted as
    already_gone, NOT a delete_error. The sweep continues."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    raw_dir = Path(cfg.paths.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    f = raw_dir / "v1.mp4"
    f.write_bytes(b"x")
    _set_mtime_days_ago(f, 20)
    _seed_video(repo)
    _seed_clip(repo, clip_id="v1_30_60", status="uploaded")

    real_unlink = os.unlink

    def _fake_unlink(p):
        raise FileNotFoundError(p)

    monkeypatch.setattr("src.retention.cleanup.os.unlink", _fake_unlink)
    result = run_all(repo, cfg, dry_run=False)
    assert result.deleted_raw == 0
    assert result.already_gone == 1
    assert result.delete_errors == []


def test_run_all_real_mode_permission_error_recorded(tmp_path, monkeypatch):
    """PermissionError on unlink → delete_errors gets one entry; sweep continues."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    raw_dir = Path(cfg.paths.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    f = raw_dir / "v1.mp4"
    f.write_bytes(b"x")
    _set_mtime_days_ago(f, 20)
    _seed_video(repo)
    _seed_clip(repo, clip_id="v1_30_60", status="uploaded")

    def _fake_unlink(p):
        raise PermissionError(f"locked: {p}")

    monkeypatch.setattr("src.retention.cleanup.os.unlink", _fake_unlink)
    result = run_all(repo, cfg, dry_run=False)
    assert result.deleted_raw == 0
    assert len(result.delete_errors) == 1
    assert "locked" in result.delete_errors[0]
    # Alert appended.
    alerts_md = (Path(cfg.paths.logs_dir) / "alerts.md").read_text(encoding="utf-8")
    assert "retention_delete_errors" in alerts_md


def test_run_all_real_mode_skips_path_outside_root(tmp_path):
    """A candidate path that resolves outside the project root is refused +
    alerted, never unlinked."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    # Plant a file OUTSIDE tmp_path, then craft a clip row pointing at it.
    outside = tmp_path.parent / "outside_root.mp4"
    outside.write_bytes(b"x")
    _set_mtime_days_ago(outside, 20)
    _seed_video(repo)
    # Mark uploaded so the clip is picked up by output_post_upload candidates;
    # but updated_at must be older than 7 days.
    _seed_clip(
        repo, clip_id="v1_30_60", status="uploaded",
        output_path=str(outside),
        updated_at="2026-01-01 00:00:00",
    )
    # We'd need this path to land in `would_delete_output_*`. The list_output_*
    # function only yields files under pending/approved roots, so this one is
    # already filtered out at enumeration. To exercise the safety net directly,
    # we test _safe_unlink in isolation.
    from src.retention.cleanup import _safe_unlink, RetentionResult
    result = RetentionResult(dry_run=False)
    ok = _safe_unlink(
        str(outside),
        root=tmp_path,
        result=result,
        logs_dir=Path(cfg.paths.logs_dir),
    )
    assert ok is False
    assert outside.exists()  # never deleted
    alerts_md = (Path(cfg.paths.logs_dir) / "alerts.md").read_text(encoding="utf-8")
    assert "retention_path_outside_root" in alerts_md


def test_run_all_dry_run_writes_nothing(tmp_path):
    """Phase 7 regression: dry_run=True still writes nothing (Phase 5 isolation)."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    raw_dir = Path(cfg.paths.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    f = raw_dir / "v1.mp4"
    f.write_bytes(b"x")
    _set_mtime_days_ago(f, 20)
    _seed_video(repo)
    _seed_clip(repo, clip_id="v1_30_60", status="uploaded")

    repo.conn.execute(
        "INSERT INTO dup_hashes (clip_id, phash, created_at) VALUES (?, ?, ?)",
        ("v1_30_60", "deadbeef", "2025-01-01 00:00:00"),
    )

    result = run_all(repo, cfg, dry_run=True, now=datetime(2026, 5, 3, tzinfo=timezone.utc))
    assert result.dry_run is True
    assert result.deleted_raw == 0
    assert result.pruned_dup_hashes == 0
    assert f.exists()
    n = repo.conn.execute("SELECT COUNT(*) FROM dup_hashes").fetchone()[0]
    assert n == 1


def test_vacuum_sentinel_gate_due_when_missing(tmp_path):
    """No sentinel → would_vacuum True → real run touches sentinel."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    sentinel = cfg.abs_path("data/.last_vacuum")
    assert not sentinel.exists()

    result = run_all(repo, cfg, dry_run=False)
    assert result.would_vacuum is True
    assert result.vacuumed is True
    assert sentinel.exists()


def test_vacuum_sentinel_gate_not_due_when_recent(tmp_path):
    """Sentinel < cfg.retention.vacuum_every_days old → would_vacuum False."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    sentinel = cfg.abs_path("data/.last_vacuum")
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("recent", encoding="utf-8")
    _set_mtime_days_ago(sentinel, 5)  # well under 30 days default

    result = run_all(repo, cfg, dry_run=False)
    assert result.would_vacuum is False
    assert result.vacuumed is False


def test_vacuum_busy_does_not_touch_sentinel(tmp_path, monkeypatch):
    """SQLITE_BUSY on VACUUM → vacuumed=False, vacuum_skipped alert,
    sentinel mtime unchanged so the next sweep retries."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    sentinel = cfg.abs_path("data/.last_vacuum")
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("old", encoding="utf-8")
    _set_mtime_days_ago(sentinel, 365)
    pre_mtime = sentinel.stat().st_mtime

    import sqlite3 as sqlite_mod

    class _BusyConn:
        def execute(self, *a, **kw):
            raise sqlite_mod.OperationalError("database is locked")

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("src.retention.cleanup.sqlite3.connect", lambda *a, **kw: _BusyConn())

    result = run_all(repo, cfg, dry_run=False)
    assert result.would_vacuum is True
    assert result.vacuumed is False
    assert sentinel.stat().st_mtime == pre_mtime  # untouched
    alerts_md = (Path(cfg.paths.logs_dir) / "alerts.md").read_text(encoding="utf-8")
    assert "vacuum_skipped" in alerts_md
