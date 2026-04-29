"""Disk-budget primitives + eviction loop."""

from pathlib import Path

from src.downloader import disk_budget
from src.state import Repository, connect, initialize_schema
from tests.conftest import StubConfig


def _seed_video(repo, vid, *, status="downloaded", updated_at=None):
    repo.discovery_upsert_video(
        video_id=vid, title=f"T-{vid}", channel="C",
        duration_seconds=600, views=1, likes=0, comments=0,
        published_at="2026-04-01T00:00:00Z",
        keyword="k", virality_score=1.0,
    )
    if status != "discovered":
        repo.set_video_status(vid, status)
    if updated_at:
        repo.conn.execute(
            "UPDATE videos SET updated_at=? WHERE video_id=?", (updated_at, vid)
        )


def _seed_clip(repo, clip_id, vid, status):
    repo.insert_clip(
        clip_id=clip_id, video_id=vid, start_s=0, end_s=30,
        hook="h", suggested_title="t", selection_method="transcript_only",
        status=status,
    )


def _make_mp4(path: Path, size: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(b"\x00" * size)


def _fresh_repo(tmp_path):
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def test_current_usage_sums_files(tmp_path):
    raw = tmp_path / "raw"
    _make_mp4(raw / "a.mp4", 1000)
    _make_mp4(raw / "b.mp4", 2500)
    (raw / "c.txt").write_bytes(b"ignore me")
    assert disk_budget.current_usage_bytes(raw) == 3500


def test_current_usage_missing_dir(tmp_path):
    assert disk_budget.current_usage_bytes(tmp_path / "nope") == 0


def test_evict_oldest_first_until_under_cap(tmp_path):
    repo = _fresh_repo(tmp_path)
    cfg = StubConfig(tmp_path, soft_cap_gb=0)  # cap = 0; anything triggers eviction
    raw = Path(cfg.paths.raw_dir)

    # Three fully-uploaded videos; evictable.
    for vid, mtime in [("vA", "2026-01-01 00:00:00"),
                       ("vB", "2026-02-01 00:00:00"),
                       ("vC", "2026-03-01 00:00:00")]:
        _seed_video(repo, vid, updated_at=mtime)
        _seed_clip(repo, f"{vid}_c1", vid, "uploaded")
        _make_mp4(raw / f"{vid}.mp4", 1000)

    report = disk_budget.evict_to_soft_cap(cfg, raw, repo)
    assert report.deleted_count == 3
    assert report.halted_reason == "under_soft_cap"
    # Oldest first
    assert "vA" in report.files_deleted[0]
    assert "vB" in report.files_deleted[1]
    assert "vC" in report.files_deleted[2]


def test_evict_skips_non_uploaded_clips(tmp_path):
    repo = _fresh_repo(tmp_path)
    cfg = StubConfig(tmp_path, soft_cap_gb=0)
    raw = Path(cfg.paths.raw_dir)

    _seed_video(repo, "vSafe", updated_at="2026-01-01 00:00:00")
    _seed_clip(repo, "c1", "vSafe", "uploaded")
    _seed_clip(repo, "c2", "vSafe", "rendered")  # not uploaded -> safety hold
    _make_mp4(raw / "vSafe.mp4", 1000)

    report = disk_budget.evict_to_soft_cap(cfg, raw, repo)
    assert report.deleted_count == 0
    assert report.halted_reason == "no_eligible_victims"
    assert (raw / "vSafe.mp4").exists()


def test_evict_skips_zero_clip_videos(tmp_path):
    """Critical safety: a downloaded video with no derivatives MUST NOT be deleted."""
    repo = _fresh_repo(tmp_path)
    cfg = StubConfig(tmp_path, soft_cap_gb=0)
    raw = Path(cfg.paths.raw_dir)

    _seed_video(repo, "vNoClips", updated_at="2026-01-01 00:00:00")
    _make_mp4(raw / "vNoClips.mp4", 1000)

    report = disk_budget.evict_to_soft_cap(cfg, raw, repo)
    assert report.deleted_count == 0
    assert report.halted_reason == "no_eligible_victims"
    assert (raw / "vNoClips.mp4").exists()


def test_evict_under_soft_cap_returns_immediately(tmp_path):
    repo = _fresh_repo(tmp_path)
    cfg = StubConfig(tmp_path, soft_cap_gb=100)  # we won't approach this
    raw = Path(cfg.paths.raw_dir)
    _make_mp4(raw / "tiny.mp4", 100)

    report = disk_budget.evict_to_soft_cap(cfg, raw, repo)
    assert report.deleted_count == 0
    assert report.halted_reason == "under_soft_cap"


def test_would_exceed_hard_cap(tmp_path):
    cfg = StubConfig(tmp_path, hard_cap_gb=0)  # zero cap; anything overflows
    raw = Path(cfg.paths.raw_dir)
    assert disk_budget.would_exceed_hard_cap(cfg, raw, 1) is True


def test_evictable_ordering_oldest_first(tmp_path):
    repo = _fresh_repo(tmp_path)
    _seed_video(repo, "newest", updated_at="2026-12-01 00:00:00")
    _seed_clip(repo, "n1", "newest", "uploaded")
    _seed_video(repo, "oldest", updated_at="2026-01-01 00:00:00")
    _seed_clip(repo, "o1", "oldest", "uploaded")
    assert repo.evictable_video_ids() == ["oldest", "newest"]
