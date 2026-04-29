"""cleanup_partial removes sidecars (.part, .f137.mp4, .info.json, .webm) but
preserves the canonical dest_path."""

from pathlib import Path

from src.downloader.ytdlp_runner import cleanup_partial


def test_removes_sidecars_keeps_dest(tmp_path):
    raw = tmp_path / "raw"; raw.mkdir()
    dest = raw / "vid1.mp4"
    dest.write_bytes(b"final")

    sidecars = [
        raw / "vid1.part",
        raw / "vid1.f137.mp4",
        raw / "vid1.f140.m4a",
        raw / "vid1.info.json",
        raw / "vid1.webm",
        raw / "vid1.ytdl",
    ]
    for s in sidecars:
        s.write_bytes(b"sidecar")

    removed = cleanup_partial(dest)
    assert removed == len(sidecars)
    assert dest.exists()
    for s in sidecars:
        assert not s.exists()


def test_does_not_touch_unrelated_files(tmp_path):
    raw = tmp_path / "raw"; raw.mkdir()
    dest = raw / "vidA.mp4"
    dest.write_bytes(b"a")

    other = raw / "vidB.mp4"
    other.write_bytes(b"b")

    cleanup_partial(dest)
    assert dest.exists()
    assert other.exists()  # different stem -> untouched


def test_handles_missing_dir(tmp_path):
    # Calling cleanup_partial against a non-existent parent must not crash.
    nonexistent = tmp_path / "nope" / "vid.mp4"
    assert cleanup_partial(nonexistent) == 0
