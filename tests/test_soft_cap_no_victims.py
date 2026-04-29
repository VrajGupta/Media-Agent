"""Soft-cap overage with no eligible victims — eviction is a no-op, runner continues."""

from pathlib import Path

from src.downloader import disk_budget
from src.state import Repository, connect, initialize_schema
from tests.conftest import StubConfig


def _setup(tmp_path):
    cfg = StubConfig(tmp_path, soft_cap_gb=0)
    conn = connect(Path(cfg.paths.state_db))
    initialize_schema(conn)
    return cfg, Repository(conn)


def test_eviction_no_eligible_victims_returns_cleanly(tmp_path):
    cfg, repo = _setup(tmp_path)
    raw = Path(cfg.paths.raw_dir)

    # Place a file but DO NOT seed any video/clip rows -> nothing is evictable.
    (raw / "orphan.mp4").write_bytes(b"\x00" * 1000)

    report = disk_budget.evict_to_soft_cap(cfg, raw, repo)
    assert report.deleted_count == 0
    assert report.halted_reason == "no_eligible_victims"
    assert report.freed_bytes == 0
    assert report.files_deleted == []
    # File untouched
    assert (raw / "orphan.mp4").exists()
