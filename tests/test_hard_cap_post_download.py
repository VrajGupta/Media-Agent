"""Post-download hard-cap re-check: a download that pushes us over the cap is reverted."""

from pathlib import Path

from src.downloader import runner
from src.downloader.ytdlp_runner import DownloadOutcome, ProbeOutcome
from src.state import Repository, connect, initialize_schema
from tests.conftest import StubConfig


def test_post_download_hard_cap_reverts(tmp_path, monkeypatch):
    """Pre-flight passes (small probe estimate); actual download exceeds cap; revert."""
    cfg = StubConfig(tmp_path, hard_cap_gb=1, soft_cap_gb=1, free_floor_gb=0)
    conn = connect(Path(cfg.paths.state_db))
    initialize_schema(conn)
    repo = Repository(conn)

    repo.discovery_upsert_video(
        video_id="vBig", title="T", channel="C",
        duration_seconds=600, views=1, likes=0, comments=0,
        published_at="2026-04-01T00:00:00Z",
        keyword="k", virality_score=1.0,
    )

    # Probe says ~1 byte so pre-flight is well under the 1 GB cap.
    monkeypatch.setattr(
        runner.ytdlp_runner, "probe",
        lambda vid, mn, mx: ProbeOutcome(1080, 1, None),
    )

    # yt-dlp writes a sparse 2 GB file; st_size reports 2 GB even though
    # no allocation happens — fast and disk-friendly for tests.
    def fake_download(vid, dest, *, min_height, max_height):
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as f:
            f.truncate(2 * 1024 * 1024 * 1024)
        return DownloadOutcome(dest, 1080, 2 * 1024 ** 3, "ok", None)

    monkeypatch.setattr(runner.ytdlp_runner, "download_one", fake_download)

    result = runner.download_one_video(cfg, repo, "vBig")
    assert result.status == "rejected_download"
    assert "hard cap" in result.detail.lower()
    assert not (Path(cfg.paths.raw_dir) / "vBig.mp4").exists()
    assert repo.get_video("vBig")["status"] == "rejected_download"
