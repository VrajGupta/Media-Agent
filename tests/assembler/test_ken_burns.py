"""P7.4 — Ken Burns argv builder (pure, no ffmpeg)."""

from pathlib import Path

from src.assembler.ken_burns import build_ken_burns_argv


def test_ken_burns_argv_contains_blurred_bg_chain(tmp_path):
    argv = build_ken_burns_argv(
        tmp_path / "logo.png",
        tmp_path / "shot_00.mp4",
    )
    fg = " ".join(argv)
    assert "gblur" in fg
    assert "overlay" in fg


def test_ken_burns_argv_contains_zoompan(tmp_path):
    argv = build_ken_burns_argv(tmp_path / "logo.png", tmp_path / "out.mp4")
    assert any("zoompan" in part for part in argv)


def test_ken_burns_argv_resolution_and_fps(tmp_path):
    argv = build_ken_burns_argv(
        tmp_path / "logo.png",
        tmp_path / "out.mp4",
        resolution=(1080, 1920),
        fps=30,
    )
    fg = " ".join(argv)
    assert "1080x1920" in fg
    assert "fps=30" in fg


def test_ken_burns_argv_nvenc_settings(tmp_path):
    argv = build_ken_burns_argv(
        tmp_path / "logo.png",
        tmp_path / "out.mp4",
        nvenc_preset="p5",
        nvenc_cq=23,
    )
    assert "h264_nvenc" in argv
    assert "p5" in argv
    assert "23" in argv


def test_ken_burns_argv_output_path(tmp_path):
    dest = tmp_path / "shot_01.mp4"
    argv = build_ken_burns_argv(tmp_path / "logo.png", dest)
    assert str(dest) in argv
