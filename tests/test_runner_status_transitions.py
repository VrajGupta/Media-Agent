"""Probe and download outcomes map to the right videos.status values."""

from pathlib import Path

from src.downloader import runner
from src.downloader.ytdlp_runner import DownloadOutcome, ProbeOutcome
from src.state import Repository, connect, initialize_schema
from tests.conftest import StubConfig


def _seed(repo, vid):
    repo.discovery_upsert_video(
        video_id=vid, title="T", channel="C",
        duration_seconds=600, views=100, likes=1, comments=1,
        published_at="2026-04-01T00:00:00Z",
        keyword="k", virality_score=1.5,
    )


def _setup(tmp_path):
    cfg = StubConfig(tmp_path)
    conn = connect(Path(cfg.paths.state_db))
    initialize_schema(conn)
    return cfg, Repository(conn)


def test_probe_rejects_format_no_download(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    _seed(repo, "v1")

    download_called = []
    monkeypatch.setattr(
        runner.ytdlp_runner, "probe",
        lambda vid, mn, mx: ProbeOutcome(None, None, None),
    )
    monkeypatch.setattr(
        runner.ytdlp_runner, "download_one",
        lambda *a, **kw: download_called.append(1) or DownloadOutcome(
            Path("x"), None, 0, "ok", None
        ),
    )

    result = runner.download_one_video(cfg, repo, "v1")
    assert result.status == "rejected_format"
    assert repo.get_video("v1")["status"] == "rejected_format"
    assert download_called == []  # critical: no bandwidth wasted


def test_probe_error_marks_rejected_download(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    _seed(repo, "v2")

    monkeypatch.setattr(
        runner.ytdlp_runner, "probe",
        lambda vid, mn, mx: ProbeOutcome(None, None, "HTTP Error 403: Forbidden"),
    )

    result = runner.download_one_video(cfg, repo, "v2")
    assert result.status == "rejected_download"
    row = repo.get_video("v2")
    assert row["status"] == "rejected_download"
    assert "403" in (row["rejection_reason"] or "")


def test_download_error_marks_rejected_download(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    _seed(repo, "v3")

    monkeypatch.setattr(
        runner.ytdlp_runner, "probe",
        lambda vid, mn, mx: ProbeOutcome(1080, 1000, None),
    )
    monkeypatch.setattr(
        runner.ytdlp_runner, "download_one",
        lambda vid, dest, *, min_height, max_height: DownloadOutcome(
            dest, None, 0, "error", "network failure"
        ),
    )

    result = runner.download_one_video(cfg, repo, "v3")
    assert result.status == "rejected_download"
    assert repo.get_video("v3")["status"] == "rejected_download"


def test_already_rejected_skipped(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    _seed(repo, "v4")
    repo.set_video_status("v4", "rejected_format", reason="manual test")

    download_called = []
    monkeypatch.setattr(
        runner.ytdlp_runner, "probe",
        lambda *a, **kw: download_called.append(1) or ProbeOutcome(1080, 1, None),
    )

    result = runner.download_one_video(cfg, repo, "v4")
    assert result.status == "already_rejected"
    assert download_called == []  # probe not called either
    assert repo.get_video("v4")["status"] == "rejected_format"  # untouched
