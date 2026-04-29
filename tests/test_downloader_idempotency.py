"""Idempotency: rerun is a no-op; orphaned file repairs status."""

from pathlib import Path

import pytest

from src.downloader import runner
from src.downloader.ytdlp_runner import DownloadOutcome, ProbeOutcome
from src.state import Repository, connect, initialize_schema
from tests.conftest import StubConfig


def _seed_discovered(repo, vid):
    repo.discovery_upsert_video(
        video_id=vid, title="T", channel="C",
        duration_seconds=600, views=100, likes=1, comments=1,
        published_at="2026-04-01T00:00:00Z",
        keyword="k", virality_score=1.5,
    )


def _make_fake_runner(monkeypatch, tmp_path):
    """Replace probe + download_one so no network call happens.

    Records every download_one invocation in `calls`.
    """
    calls = []

    def fake_probe(video_id, min_h, max_h):
        return ProbeOutcome(available_height=1080, filesize_approx_bytes=1000, error=None)

    def fake_download(video_id, dest_path, *, min_height, max_height):
        calls.append(video_id)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"\x00" * 1000)
        return DownloadOutcome(
            path=dest_path, height=1080, filesize_bytes=1000,
            status="ok", error_message=None,
        )

    monkeypatch.setattr(runner.ytdlp_runner, "probe", fake_probe)
    monkeypatch.setattr(runner.ytdlp_runner, "download_one", fake_download)
    return calls


def test_second_run_skips(tmp_path, monkeypatch):
    cfg = StubConfig(tmp_path)
    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn); repo = Repository(conn)
    _seed_discovered(repo, "vid1")
    calls = _make_fake_runner(monkeypatch, tmp_path)

    r1 = runner.download_one_video(cfg, repo, "vid1")
    assert r1.status == "ok"
    assert len(calls) == 1

    r2 = runner.download_one_video(cfg, repo, "vid1")
    assert r2.status == "skipped"
    assert len(calls) == 1  # download NOT called again


def test_orphan_repair(tmp_path, monkeypatch):
    """File present + status='discovered' (e.g. crash before status flip) -> repair."""
    cfg = StubConfig(tmp_path)
    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn); repo = Repository(conn)
    _seed_discovered(repo, "vidOrphan")

    # Simulate the orphan: file exists but DB still says discovered.
    raw = Path(cfg.paths.raw_dir)
    (raw / "vidOrphan.mp4").write_bytes(b"\x00" * 1000)

    calls = _make_fake_runner(monkeypatch, tmp_path)
    result = runner.download_one_video(cfg, repo, "vidOrphan")

    assert result.status == "repaired"
    assert len(calls) == 0  # no re-download
    assert repo.get_video("vidOrphan")["status"] == "downloaded"


def test_missing_video_returns_missing(tmp_path, monkeypatch):
    cfg = StubConfig(tmp_path)
    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn); repo = Repository(conn)
    _make_fake_runner(monkeypatch, tmp_path)

    result = runner.download_one_video(cfg, repo, "doesNotExist")
    assert result.status == "missing"
