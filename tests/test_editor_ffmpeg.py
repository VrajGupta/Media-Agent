"""ffmpeg argv + filtergraph + path-escape tests. No subprocess invoked."""

from __future__ import annotations

from pathlib import Path

from src.editor.ffmpeg_runner import (
    build_ffmpeg_argv,
    build_filtergraph,
    escape_ass_filter_path,
)


# ---- filter-path escape -----------------------------------------------------


def test_windows_drive_path_escape():
    """Drive colons must be escaped; backslashes doubled; whole arg in single quotes."""
    s = escape_ass_filter_path(r"C:\Users\foo\bar.ass")
    assert s.startswith("'")
    assert s.endswith("'")
    assert "C\\:" in s              # colon escaped
    assert "\\\\Users\\\\foo" in s  # backslashes doubled


def test_posix_path_escape():
    s = escape_ass_filter_path("/tmp/x.ass")
    assert s == "'/tmp/x.ass'"


def test_path_with_comma_and_apostrophe():
    s = escape_ass_filter_path("/tmp/joe's,clip.ass")
    assert "\\," in s
    assert "\\'" in s


# ---- filtergraph contents ---------------------------------------------------


def test_filtergraph_contains_required_filters(tmp_path):
    ass = tmp_path / "x.ass"
    ass.write_text("")
    fg = build_filtergraph(ass)
    assert "force_original_aspect_ratio=increase" in fg
    assert "crop=1080:960" in fg
    assert "vstack=inputs=2" in fg
    assert "ass=" in fg
    assert "loudnorm=I=-14" in fg


def test_filtergraph_does_not_contain_aspect_strip_crop(tmp_path):
    """Regression: pre-revision draft had crop=in_w:in_h*9/16 — wrong on landscape input."""
    ass = tmp_path / "x.ass"
    ass.write_text("")
    fg = build_filtergraph(ass)
    assert "in_w:in_h*9/16" not in fg


def test_top_and_bottom_chains_use_identical_scale_crop(tmp_path):
    """Both panes use the same scale-fill + center-crop chain."""
    ass = tmp_path / "x.ass"
    ass.write_text("")
    fg = build_filtergraph(ass)
    # Both [0:v] and [1:v] should be followed by the same scale + crop pair.
    assert "[0:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960[top]" in fg
    assert "[1:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960[bot]" in fg


# ---- argv structure ---------------------------------------------------------


def test_argv_is_list_with_seeking_before_each_input(tmp_path):
    argv = build_ffmpeg_argv(
        ffmpeg_bin="ffmpeg",
        source_path=Path("/data/raw/v1.mp4"),
        source_start_s=10.5,
        duration_s=30.0,
        gameplay_path=Path("/data/gameplay/subway.mp4"),
        gameplay_offset_s=120.0,
        ass_path=tmp_path / "v1.ass",
        output_tmp_path=tmp_path / "out.tmp.mp4",
    )
    assert isinstance(argv, list)
    assert all(isinstance(x, str) for x in argv)

    # Find positions of -ss and -i.
    ss_idx = [i for i, a in enumerate(argv) if a == "-ss"]
    i_idx = [i for i, a in enumerate(argv) if a == "-i"]
    assert len(ss_idx) == 2
    assert len(i_idx) == 2
    # Each -ss must precede its corresponding -i.
    assert ss_idx[0] < i_idx[0]
    assert ss_idx[1] < i_idx[1]
    assert ss_idx[1] > i_idx[0]   # second -ss is between the two inputs


def test_argv_does_not_contain_ss_inside_filtergraph(tmp_path):
    """-ss must never appear inside -filter_complex argument."""
    argv = build_ffmpeg_argv(
        ffmpeg_bin="ffmpeg",
        source_path=Path("/x.mp4"),
        source_start_s=5.0,
        duration_s=30.0,
        gameplay_path=Path("/g.mp4"),
        gameplay_offset_s=0.0,
        ass_path=tmp_path / "x.ass",
        output_tmp_path=tmp_path / "out.tmp.mp4",
    )
    fc_idx = argv.index("-filter_complex")
    filtergraph = argv[fc_idx + 1]
    assert "-ss" not in filtergraph


def test_argv_includes_nvenc_settings(tmp_path):
    argv = build_ffmpeg_argv(
        ffmpeg_bin="ffmpeg",
        source_path=Path("/x.mp4"),
        source_start_s=0.0,
        duration_s=30.0,
        gameplay_path=Path("/g.mp4"),
        gameplay_offset_s=0.0,
        ass_path=tmp_path / "x.ass",
        output_tmp_path=tmp_path / "out.tmp.mp4",
        nvenc_preset="p5",
        nvenc_cq=23,
    )
    assert "h264_nvenc" in argv
    assert "p5" in argv
    assert "23" in argv
    assert "+faststart" in argv
