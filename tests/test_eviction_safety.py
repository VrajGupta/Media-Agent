"""Eviction safety property — never delete a raw mp4 whose derivatives aren't all uploaded."""

from pathlib import Path

from src.downloader import disk_budget
from src.state import Repository, connect, initialize_schema
from tests.conftest import StubConfig


def _seed(repo, vid):
    repo.discovery_upsert_video(
        video_id=vid, title="T", channel="C",
        duration_seconds=600, views=1, likes=0, comments=0,
        published_at="2026-04-01T00:00:00Z",
        keyword="k", virality_score=1.0,
    )
    repo.set_video_status(vid, "downloaded")


def _seed_clip(repo, clip_id, vid, status):
    repo.insert_clip(
        clip_id=clip_id, video_id=vid, start_s=0, end_s=30,
        hook="h", suggested_title="t", selection_method="transcript_only",
        status=status,
    )


def _make_mp4(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)


def _setup(tmp_path):
    cfg = StubConfig(tmp_path, soft_cap_gb=0)
    conn = connect(Path(cfg.paths.state_db))
    initialize_schema(conn)
    return cfg, Repository(conn)


def test_skip_when_one_clip_unfinished(tmp_path):
    cfg, repo = _setup(tmp_path)
    raw = Path(cfg.paths.raw_dir)
    _seed(repo, "vSafe")
    _seed_clip(repo, "c1", "vSafe", "uploaded")
    _seed_clip(repo, "c2", "vSafe", "rendered")  # NOT uploaded
    _make_mp4(raw / "vSafe.mp4", 1000)

    report = disk_budget.evict_to_soft_cap(cfg, raw, repo)
    assert (raw / "vSafe.mp4").exists()
    assert report.deleted_count == 0


def test_skip_when_zero_clips(tmp_path):
    """Critical: a downloaded video with no derivatives MUST NOT be deleted.

    This test is the user's explicit safety property — the 'has_unfinished_clips'
    helper would have returned false for zero-clip videos and made them deletable.
    is_raw_evictable closes that hole.
    """
    cfg, repo = _setup(tmp_path)
    raw = Path(cfg.paths.raw_dir)
    _seed(repo, "vBare")
    _make_mp4(raw / "vBare.mp4", 1000)

    report = disk_budget.evict_to_soft_cap(cfg, raw, repo)
    assert (raw / "vBare.mp4").exists()
    assert report.deleted_count == 0


def test_is_raw_evictable_matrix(tmp_path):
    cfg, repo = _setup(tmp_path)
    _seed(repo, "vNoClips")
    assert repo.is_raw_evictable("vNoClips") is False

    _seed(repo, "vMixed")
    _seed_clip(repo, "m1", "vMixed", "uploaded")
    _seed_clip(repo, "m2", "vMixed", "rendered")
    assert repo.is_raw_evictable("vMixed") is False

    _seed(repo, "vAllUp")
    _seed_clip(repo, "a1", "vAllUp", "uploaded")
    _seed_clip(repo, "a2", "vAllUp", "uploaded")
    assert repo.is_raw_evictable("vAllUp") is True
