"""P7.4 — Ken Burns argv builder (pure, no ffmpeg). Issue 33: gradient bg + no stretch."""

from pathlib import Path

from PIL import Image

from src.assembler.ken_burns import (
    build_ken_burns_argv,
    clamp_dark_for_subtitles,
    dominant_color,
)


def _filter_complex(argv: list[str]) -> str:
    idx = argv.index("-filter_complex")
    return argv[idx + 1]


def _wide_test_image(path: Path) -> Path:
    Image.new("RGB", (1920, 1080), color=(100, 150, 200)).save(path)
    return path


def test_ken_burns_zoompan_does_not_force_full_frame_on_foreground(tmp_path):
    """Regression: zoompan s=WxH after decrease-scale caused ~3x vertical squash."""
    img = _wide_test_image(tmp_path / "wide.png")
    fg = _filter_complex(build_ken_burns_argv(img, tmp_path / "out.mp4"))
    fg_branch = fg.split("force_original_aspect_ratio=decrease,")[1].split("[v_fg]")[0]
    assert "s=1080x1920" not in fg_branch


def test_dominant_color_returns_plausible_rgb(tmp_path):
    path = tmp_path / "blue.png"
    Image.new("RGB", (400, 300), color=(20, 40, 200)).save(path)
    r, g, b = dominant_color(path)
    assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255
    assert b > r and b > g


def test_clamp_dark_for_subtitles_limits_bright_input():
    r, g, b = clamp_dark_for_subtitles((255, 255, 255), max_luma=45, max_saturation=0.35)
    assert max(r, g, b) <= 45
    assert min(r, g, b) >= 0


def test_ken_burns_argv_uses_gradient_background_not_blur(tmp_path):
    img = _wide_test_image(tmp_path / "wide.png")
    fg = _filter_complex(build_ken_burns_argv(img, tmp_path / "out.mp4"))
    assert "gblur" not in fg
    assert "blend=all_expr" in fg
    assert "color=c=0x" in fg


def test_ken_burns_argv_contains_zoompan(tmp_path):
    img = _wide_test_image(tmp_path / "wide.png")
    argv = build_ken_burns_argv(img, tmp_path / "out.mp4")
    assert any("zoompan" in part for part in argv)


def test_ken_burns_argv_resolution_and_fps(tmp_path):
    img = _wide_test_image(tmp_path / "wide.png")
    argv = build_ken_burns_argv(
        img,
        tmp_path / "out.mp4",
        resolution=(1080, 1920),
        fps=30,
        duration_s=4.0,
    )
    fg = _filter_complex(argv)
    assert "1080x1920" in fg
    assert "fps=30" in fg
    assert "-t" in argv and argv[argv.index("-t") + 1] == "4.0"


def test_ken_burns_argv_nvenc_settings(tmp_path):
    img = _wide_test_image(tmp_path / "wide.png")
    argv = build_ken_burns_argv(
        img,
        tmp_path / "out.mp4",
        nvenc_preset="p5",
        nvenc_cq=23,
    )
    assert "h264_nvenc" in argv
    assert "p5" in argv
    assert "23" in argv


def test_ken_burns_argv_output_path(tmp_path):
    img = _wide_test_image(tmp_path / "wide.png")
    dest = tmp_path / "shot_01.mp4"
    argv = build_ken_burns_argv(img, dest)
    assert str(dest) in argv
