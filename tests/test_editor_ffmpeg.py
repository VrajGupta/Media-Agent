"""ffmpeg argv + filtergraph + path-escape tests (Pivot.3 — full-screen
blurred-bg + dialogue reverb + background music). No subprocess invoked.
"""

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
    assert "C\\:" in s
    assert "\\\\Users\\\\foo" in s


def test_posix_path_escape():
    s = escape_ass_filter_path("/tmp/x.ass")
    assert s == "'/tmp/x.ass'"


def test_path_with_comma_and_apostrophe():
    s = escape_ass_filter_path("/tmp/joe's,clip.ass")
    assert "\\," in s
    assert "\\'" in s


# ---- filtergraph contents (new pivot.3 layout) ------------------------------


def test_filtergraph_contains_split_and_blur(tmp_path):
    ass = tmp_path / "x.ass"
    ass.write_text("")
    fg = build_filtergraph(ass_path=ass, duration_s=30.0)
    assert "[0:v]split=2" in fg
    assert "gblur=sigma=20" in fg


def test_filtergraph_foreground_is_1080x608(tmp_path):
    ass = tmp_path / "x.ass"
    ass.write_text("")
    fg = build_filtergraph(ass_path=ass, duration_s=30.0)
    assert "scale=1080:608:force_original_aspect_ratio=decrease" in fg


def test_filtergraph_uses_overlay_centered_not_vstack(tmp_path):
    """Pivot.3: split-screen vstack is gone; overlay (W-w)/2:(H-h)/2 is the new layout."""
    ass = tmp_path / "x.ass"
    ass.write_text("")
    fg = build_filtergraph(ass_path=ass, duration_s=30.0)
    assert "vstack" not in fg
    assert "overlay=(W-w)/2:(H-h)/2" in fg


def test_filtergraph_includes_ass_burn_at_end(tmp_path):
    ass = tmp_path / "x.ass"
    ass.write_text("")
    fg = build_filtergraph(ass_path=ass, duration_s=30.0)
    assert "ass=" in fg
    # ASS comes AFTER the overlay (burned on the composite, not the bg).
    assert fg.index("overlay=") < fg.index("ass=")


def test_filtergraph_dialogue_chain_has_aecho_when_enabled(tmp_path):
    ass = tmp_path / "x.ass"
    ass.write_text("")
    fg = build_filtergraph(
        ass_path=ass, duration_s=30.0,
        dialogue_reverb_enabled=True,
        dialogue_reverb_aecho="0.8:0.88:60:0.4",
    )
    assert "aecho=0.8:0.88:60:0.4" in fg


def test_filtergraph_dialogue_chain_has_no_aecho_when_disabled(tmp_path):
    ass = tmp_path / "x.ass"
    ass.write_text("")
    fg = build_filtergraph(
        ass_path=ass, duration_s=30.0,
        dialogue_reverb_enabled=False,
    )
    assert "aecho=" not in fg


def test_filtergraph_music_chain_uses_aloop_atrim_volume_amix(tmp_path):
    ass = tmp_path / "x.ass"
    ass.write_text("")
    fg = build_filtergraph(
        ass_path=ass, duration_s=42.5,
        music_enabled=True,
        music_volume_db=-15.0,
    )
    assert "[1:a]aloop=loop=-1" in fg
    assert "atrim=0:42.500" in fg
    assert "volume=-15dB" in fg
    assert "amix=inputs=2:duration=first:normalize=0" in fg
    assert "[a_voice]" in fg
    assert "[a_music]" in fg


def test_filtergraph_no_music_chain_when_disabled(tmp_path):
    ass = tmp_path / "x.ass"
    ass.write_text("")
    fg = build_filtergraph(
        ass_path=ass, duration_s=30.0,
        music_enabled=False,
    )
    assert "[1:a]" not in fg
    assert "amix" not in fg
    assert "aloop" not in fg
    # But dialogue chain ends at [a] directly.
    assert "[a]" in fg


def test_filtergraph_blur_sigma_configurable(tmp_path):
    ass = tmp_path / "x.ass"
    ass.write_text("")
    fg = build_filtergraph(ass_path=ass, duration_s=30.0, blurred_bg_sigma=35)
    assert "gblur=sigma=35" in fg
    assert "gblur=sigma=20" not in fg


# ---- argv structure ---------------------------------------------------------


def test_argv_no_music_has_one_input(tmp_path):
    argv = build_ffmpeg_argv(
        ffmpeg_bin="ffmpeg",
        source_path=Path("/data/raw/v1.mp4"),
        source_start_s=10.5,
        duration_s=30.0,
        ass_path=tmp_path / "v1.ass",
        output_tmp_path=tmp_path / "out.tmp.mp4",
        music_path=None,
    )
    assert isinstance(argv, list)
    assert all(isinstance(x, str) for x in argv)
    i_idx = [i for i, a in enumerate(argv) if a == "-i"]
    assert len(i_idx) == 1


def test_argv_with_music_has_two_inputs(tmp_path):
    argv = build_ffmpeg_argv(
        ffmpeg_bin="ffmpeg",
        source_path=Path("/data/raw/v1.mp4"),
        source_start_s=10.5,
        duration_s=30.0,
        ass_path=tmp_path / "v1.ass",
        output_tmp_path=tmp_path / "out.tmp.mp4",
        music_path=Path("/data/music/phonk.mp3"),
    )
    i_idx = [i for i, a in enumerate(argv) if a == "-i"]
    assert len(i_idx) == 2
    # First -i is source video (argv slot is i_idx + 1), second is music.
    assert "v1.mp4" in argv[i_idx[0] + 1]
    assert "phonk.mp3" in argv[i_idx[1] + 1]


def test_argv_seek_before_source_input_only(tmp_path):
    """-ss precedes the source -i; music input does not require seek by default."""
    argv = build_ffmpeg_argv(
        ffmpeg_bin="ffmpeg",
        source_path=Path("/x.mp4"),
        source_start_s=5.0,
        duration_s=30.0,
        ass_path=tmp_path / "x.ass",
        output_tmp_path=tmp_path / "out.tmp.mp4",
        music_path=None,
    )
    ss_idx = [i for i, a in enumerate(argv) if a == "-ss"]
    i_idx = [i for i, a in enumerate(argv) if a == "-i"]
    assert len(ss_idx) == 1
    assert len(i_idx) == 1
    assert ss_idx[0] < i_idx[0]


def test_argv_does_not_contain_ss_inside_filtergraph(tmp_path):
    """-ss must never appear inside -filter_complex argument."""
    argv = build_ffmpeg_argv(
        ffmpeg_bin="ffmpeg",
        source_path=Path("/x.mp4"),
        source_start_s=5.0,
        duration_s=30.0,
        ass_path=tmp_path / "x.ass",
        output_tmp_path=tmp_path / "out.tmp.mp4",
        music_path=Path("/m.mp3"),
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
        ass_path=tmp_path / "x.ass",
        output_tmp_path=tmp_path / "out.tmp.mp4",
        nvenc_preset="p5",
        nvenc_cq=23,
    )
    assert "h264_nvenc" in argv
    assert "p5" in argv
    assert "23" in argv
    assert "+faststart" in argv


def test_argv_maps_video_and_audio_outputs(tmp_path):
    argv = build_ffmpeg_argv(
        ffmpeg_bin="ffmpeg",
        source_path=Path("/x.mp4"),
        source_start_s=0.0,
        duration_s=30.0,
        ass_path=tmp_path / "x.ass",
        output_tmp_path=tmp_path / "out.tmp.mp4",
    )
    map_idx = [i for i, a in enumerate(argv) if a == "-map"]
    assert len(map_idx) == 2
    assert argv[map_idx[0] + 1] == "[v_out]"
    assert argv[map_idx[1] + 1] == "[a]"
