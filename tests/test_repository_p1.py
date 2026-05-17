"""P1 — Repository interface improvements.

Tests that verify:
1. tx() yields repo (not conn) — callers can't escape to raw SQL via the context var
2. Quota methods exist on Repository (QuotaLedger absorbed)
3. clip_has_youtube_id() convenience predicate
4. get_clip() named method replaces repo.conn.execute("SELECT * FROM clips WHERE clip_id=?")
5. Named delete helpers for retention cleanup
6. set_clip_publish_at() for uploader
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.state import Repository, connect, initialize_schema


@pytest.fixture
def repo(tmp_path):
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _insert_clip(repo: Repository, clip_id: str, status: str = "quality_pass", youtube_id: str | None = None):
    repo.upsert_video(
        video_id="vid1", title="Test Video", channel="ch", duration_seconds=120,
        views=1000, likes=100, comments=10, published_at="2026-01-01", keyword="test",
        virality_score=1.0, status="discovered",
    )
    repo.insert_clip(
        clip_id=clip_id,
        video_id="vid1",
        start_s=0.0,
        end_s=30.0,
        hook="Hook text",
        suggested_title="Test Clip",
        selection_method="heatmap_aided",
        status=status,
    )
    if youtube_id:
        repo.set_clip_youtube_id(clip_id, youtube_id)


# ---------------------------------------------------------------------------
# tx() yields repo, not conn
# ---------------------------------------------------------------------------


def test_tx_yields_repo_instance(repo):
    with repo.tx() as ctx:
        assert ctx is repo


def _ensure_video(repo: Repository) -> None:
    repo.upsert_video(
        video_id="v1", title="V", channel="c", duration_seconds=60,
        views=0, likes=0, comments=0, published_at="2026-01-01", keyword="k",
        virality_score=0.0, status="discovered",
    )


def _clip_kwargs(clip_id: str, status: str = "quality_pass") -> dict:
    return dict(clip_id=clip_id, video_id="v1", start_s=0.0, end_s=5.0,
                hook="H", suggested_title="T", selection_method="heatmap_aided", status=status)


def test_tx_commits_on_success(repo):
    _ensure_video(repo)
    with repo.tx():
        repo.insert_clip(**_clip_kwargs("c1"))
    row = repo.get_clip("c1")
    assert row is not None


def test_tx_rolls_back_on_exception(repo):
    _ensure_video(repo)
    with pytest.raises(ValueError):
        with repo.tx():
            repo.insert_clip(**_clip_kwargs("c2"))
            raise ValueError("abort!")
    assert repo.get_clip("c2") is None


# ---------------------------------------------------------------------------
# get_clip() — named lookup replacing repo.conn.execute("SELECT * ... WHERE clip_id=?")
# ---------------------------------------------------------------------------


def test_get_clip_returns_row(repo):
    _insert_clip(repo, "c3")
    row = repo.get_clip("c3")
    assert row is not None
    assert row["clip_id"] == "c3"


def test_get_clip_returns_none_for_missing(repo):
    assert repo.get_clip("nonexistent") is None


# ---------------------------------------------------------------------------
# clip_has_youtube_id() — orphan marker consistency check
# ---------------------------------------------------------------------------


def test_clip_has_youtube_id_true(repo):
    _insert_clip(repo, "c4", youtube_id="yt_abc")
    assert repo.clip_has_youtube_id("c4") is True


def test_clip_has_youtube_id_false_when_null(repo):
    _insert_clip(repo, "c5")
    assert repo.clip_has_youtube_id("c5") is False


def test_clip_has_youtube_id_false_when_missing(repo):
    assert repo.clip_has_youtube_id("no_such_clip") is False


# ---------------------------------------------------------------------------
# set_clip_publish_at() — uploader's narrow publish-at write
# ---------------------------------------------------------------------------


def test_set_clip_publish_at_updates_field(repo):
    _insert_clip(repo, "c6")
    repo.set_clip_publish_at("c6", "2026-06-01T09:00:00Z")
    row = repo.get_clip("c6")
    assert row["publish_at_utc"] == "2026-06-01T09:00:00Z"


# ---------------------------------------------------------------------------
# Quota methods absorbed from QuotaLedger
# ---------------------------------------------------------------------------


def test_quota_record_and_today_total(repo):
    repo.quota_record("videos.insert", 1600)
    repo.quota_record("videos.insert", 1600)
    assert repo.quota_today_total() == 3200


def test_quota_today_total_zero_when_empty(repo):
    assert repo.quota_today_total() == 0


def test_quota_would_exceed_true(repo):
    repo.quota_record("videos.insert", 8500)
    assert repo.quota_would_exceed(600, ceiling=9000) is True


def test_quota_would_exceed_false(repo):
    repo.quota_record("videos.insert", 1000)
    assert repo.quota_would_exceed(1000, ceiling=9000) is False


def test_quota_would_exceed_exact_boundary(repo):
    repo.quota_record("videos.insert", 8400)
    # 8400 + 600 = 9000 = ceiling → NOT exceeded (strictly greater)
    assert repo.quota_would_exceed(600, ceiling=9000) is False
    # 8400 + 601 = 9001 > ceiling → exceeded
    assert repo.quota_would_exceed(601, ceiling=9000) is True


# ---------------------------------------------------------------------------
# delete_dup_hashes_before / delete_quota_usage_before — retention helpers
# ---------------------------------------------------------------------------


def test_delete_dup_hashes_before_removes_old_rows(repo):
    _insert_clip(repo, "c7")
    # Insert a dup_hash row with an old timestamp
    repo.conn.execute(
        "INSERT INTO dup_hashes (clip_id, phash, audio_fp, created_at) "
        "VALUES (?, ?, NULL, datetime('now', '-100 days'))",
        ("c7", "deadbeef"),
    )
    deleted = repo.delete_dup_hashes_before("2026-06-01 00:00:00")
    assert deleted >= 1


def test_delete_quota_usage_before_removes_old_rows(repo):
    repo.conn.execute(
        "INSERT INTO quota_usage (date, endpoint, units) VALUES (?, ?, ?)",
        ("2025-01-01", "videos.insert", 1600),
    )
    deleted = repo.delete_quota_usage_before("2026-01-01")
    assert deleted >= 1
