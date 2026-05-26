"""Unit tests for assembler.build — pure argv/list construction, no ffmpeg invoked."""
from pathlib import Path

import pytest

from src.assembler.build import build_assembler_argv, write_concat_list


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _shot_paths(n: int, tmp_path: Path) -> list[Path]:
    paths = []
    for i in range(n):
        p = tmp_path / f"shot_{i:02d}.mp4"
        p.write_bytes(b"fake")
        paths.append(p)
    return paths


# ---------------------------------------------------------------------------
# write_concat_list
# ---------------------------------------------------------------------------


def test_write_concat_list_returns_dest(tmp_path):
    shots = _shot_paths(3, tmp_path)
    dest = tmp_path / "list.txt"
    result = write_concat_list(shots, dest)
    assert result == dest


def test_write_concat_list_correct_format(tmp_path):
    shots = _shot_paths(2, tmp_path)
    dest = tmp_path / "list.txt"
    write_concat_list(shots, dest)
    lines = dest.read_text().strip().splitlines()
    assert len(lines) == 2
    for line, shot in zip(lines, shots):
        assert line.startswith("file '")
        assert str(shot) in line


def test_write_concat_list_all_shots_present(tmp_path):
    shots = _shot_paths(4, tmp_path)
    dest = tmp_path / "list.txt"
    write_concat_list(shots, dest)
    content = dest.read_text()
    for shot in shots:
        assert str(shot) in content


# ---------------------------------------------------------------------------
# build_assembler_argv — tracer bullet
# ---------------------------------------------------------------------------


def test_build_argv_returns_list_of_strings(tmp_path):
    shots = _shot_paths(2, tmp_path)
    concat_list = tmp_path / "list.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"
    narration.write_bytes(b"fake")
    output = tmp_path / "out.mp4"

    argv = build_assembler_argv(concat_list, narration, output, total_duration_s=10.0)

    assert isinstance(argv, list)
    assert all(isinstance(a, str) for a in argv)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def test_build_argv_has_concat_input(tmp_path):
    shots = _shot_paths(2, tmp_path)
    concat_list = tmp_path / "list.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"; narration.write_bytes(b"fake")
    output = tmp_path / "out.mp4"

    argv = build_assembler_argv(concat_list, narration, output, total_duration_s=10.0)

    assert "-f" in argv
    idx = argv.index("-f")
    assert argv[idx + 1] == "concat"
    assert str(concat_list) in argv


def test_build_argv_has_narration_input(tmp_path):
    shots = _shot_paths(2, tmp_path)
    concat_list = tmp_path / "list.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"; narration.write_bytes(b"fake")
    output = tmp_path / "out.mp4"

    argv = build_assembler_argv(concat_list, narration, output, total_duration_s=10.0)

    assert str(narration) in argv


def test_build_argv_with_music_has_three_inputs(tmp_path):
    shots = _shot_paths(2, tmp_path)
    concat_list = tmp_path / "list.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"; narration.write_bytes(b"fake")
    music = tmp_path / "music.mp3"; music.write_bytes(b"fake")
    output = tmp_path / "out.mp4"

    argv = build_assembler_argv(concat_list, narration, output, total_duration_s=10.0, music_path=music)

    # Three -i flags: concat list, narration, music
    i_positions = [i for i, a in enumerate(argv) if a == "-i"]
    assert len(i_positions) == 3


def test_build_argv_without_music_has_two_inputs(tmp_path):
    shots = _shot_paths(2, tmp_path)
    concat_list = tmp_path / "list.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"; narration.write_bytes(b"fake")
    output = tmp_path / "out.mp4"

    argv = build_assembler_argv(concat_list, narration, output, total_duration_s=10.0)

    i_positions = [i for i, a in enumerate(argv) if a == "-i"]
    assert len(i_positions) == 2


# ---------------------------------------------------------------------------
# Output mapping
# ---------------------------------------------------------------------------


def test_build_argv_maps_video_stream(tmp_path):
    shots = _shot_paths(2, tmp_path)
    concat_list = tmp_path / "list.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"; narration.write_bytes(b"fake")
    output = tmp_path / "out.mp4"

    argv = build_assembler_argv(concat_list, narration, output, total_duration_s=10.0)

    assert "[v_out]" in argv


def test_build_argv_maps_audio_stream(tmp_path):
    shots = _shot_paths(2, tmp_path)
    concat_list = tmp_path / "list.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"; narration.write_bytes(b"fake")
    output = tmp_path / "out.mp4"

    argv = build_assembler_argv(concat_list, narration, output, total_duration_s=10.0)

    assert "[a]" in argv


def test_build_argv_uses_nvenc(tmp_path):
    shots = _shot_paths(2, tmp_path)
    concat_list = tmp_path / "list.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"; narration.write_bytes(b"fake")
    output = tmp_path / "out.mp4"

    argv = build_assembler_argv(concat_list, narration, output, total_duration_s=10.0)

    assert "h264_nvenc" in argv


def test_build_argv_output_path_is_last(tmp_path):
    shots = _shot_paths(2, tmp_path)
    concat_list = tmp_path / "list.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"; narration.write_bytes(b"fake")
    output = tmp_path / "out.mp4"

    argv = build_assembler_argv(concat_list, narration, output, total_duration_s=10.0)

    assert argv[-1] == str(output)


# ---------------------------------------------------------------------------
# Filtergraph shape
# ---------------------------------------------------------------------------


def test_build_argv_without_music_no_amix_in_filtergraph(tmp_path):
    shots = _shot_paths(2, tmp_path)
    concat_list = tmp_path / "list.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"; narration.write_bytes(b"fake")
    output = tmp_path / "out.mp4"

    argv = build_assembler_argv(concat_list, narration, output, total_duration_s=10.0)

    fg_idx = argv.index("-filter_complex")
    filtergraph = argv[fg_idx + 1]
    assert "amix" not in filtergraph


def test_build_argv_with_music_has_amix_in_filtergraph(tmp_path):
    shots = _shot_paths(2, tmp_path)
    concat_list = tmp_path / "list.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"; narration.write_bytes(b"fake")
    music = tmp_path / "music.mp3"; music.write_bytes(b"fake")
    output = tmp_path / "out.mp4"

    argv = build_assembler_argv(concat_list, narration, output, total_duration_s=10.0, music_path=music)

    fg_idx = argv.index("-filter_complex")
    filtergraph = argv[fg_idx + 1]
    assert "amix" in filtergraph


# ---------------------------------------------------------------------------
# Subtitle burn-in (ass_path)
# ---------------------------------------------------------------------------


def test_build_argv_with_ass_path_has_ass_filter(tmp_path):
    shots = _shot_paths(2, tmp_path)
    concat_list = tmp_path / "list.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"; narration.write_bytes(b"fake")
    ass = tmp_path / "subs.ass"; ass.write_text("[Script Info]\n", encoding="utf-8")
    output = tmp_path / "out.mp4"

    argv = build_assembler_argv(concat_list, narration, output, total_duration_s=10.0, ass_path=ass)

    fg_idx = argv.index("-filter_complex")
    filtergraph = argv[fg_idx + 1]
    assert "ass=" in filtergraph


def test_build_argv_without_ass_path_no_ass_filter(tmp_path):
    shots = _shot_paths(2, tmp_path)
    concat_list = tmp_path / "list.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"; narration.write_bytes(b"fake")
    output = tmp_path / "out.mp4"

    argv = build_assembler_argv(concat_list, narration, output, total_duration_s=10.0)

    fg_idx = argv.index("-filter_complex")
    filtergraph = argv[fg_idx + 1]
    assert "ass=" not in filtergraph


# ---------------------------------------------------------------------------
# Shot normalization + crossfade (Issue 22)
# ---------------------------------------------------------------------------


def _filtergraph(argv: list[str]) -> str:
    return argv[argv.index("-filter_complex") + 1]


def test_crossfade_chain_normalizes_inputs_not_raw_into_xfade(tmp_path):
    shots = _shot_paths(2, tmp_path)
    concat_list = tmp_path / "list.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"
    narration.write_bytes(b"fake")
    output = tmp_path / "out.mp4"

    argv = build_assembler_argv(
        concat_list,
        narration,
        output,
        total_duration_s=7.75,
        shot_paths=shots,
        crossfade_enabled=True,
        crossfade_duration_s=0.25,
        shot_durations_s=[4.0, 4.0],
        resolution=(1080, 1920),
        fps=30,
    )
    fg = _filtergraph(argv)
    assert "scale=1080:1920" in fg
    assert "[vn0][vn1]xfade" in fg
    assert "[0:v][1:v]xfade" not in fg


@pytest.mark.parametrize("n_shots", [2, 3, 4])
def test_crossfade_offsets_unchanged_with_normalization(tmp_path, n_shots):
    shots = _shot_paths(n_shots, tmp_path)
    concat_list = tmp_path / "list.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"
    narration.write_bytes(b"fake")
    output = tmp_path / "out.mp4"
    durations = [4.0] * n_shots

    argv = build_assembler_argv(
        concat_list,
        narration,
        output,
        total_duration_s=sum(durations) - 0.25 * (n_shots - 1),
        shot_paths=shots,
        crossfade_enabled=True,
        crossfade_duration_s=0.25,
        shot_durations_s=durations,
        resolution=(1080, 1920),
        fps=30,
    )
    fg = _filtergraph(argv)
    assert "offset=3.75" in fg
    if n_shots >= 3:
        assert "offset=7.5" in fg
    if n_shots >= 4:
        assert "offset=11.25" in fg


def test_crossfade_off_multi_input_uses_concat_filter_not_demuxer(tmp_path):
    shots = _shot_paths(2, tmp_path)
    concat_list = tmp_path / "list.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"
    narration.write_bytes(b"fake")
    output = tmp_path / "out.mp4"

    argv = build_assembler_argv(
        concat_list,
        narration,
        output,
        total_duration_s=8.0,
        shot_paths=shots,
        crossfade_enabled=False,
        resolution=(1080, 1920),
        fps=30,
    )

    assert "-f" not in argv or argv[argv.index("-f") + 1] != "concat"
    i_positions = [i for i, a in enumerate(argv) if a == "-i"]
    assert len(i_positions) == 3  # two shots + narration
    fg = _filtergraph(argv)
    assert "concat=n=2:v=1:a=0" in fg
    assert "[vn0][vn1]concat" in fg
    assert "[2:a]" in fg


def test_single_input_legacy_filtergraph_unchanged(tmp_path):
    shots = _shot_paths(1, tmp_path)
    concat_list = tmp_path / "list.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"
    narration.write_bytes(b"fake")
    output = tmp_path / "out.mp4"

    baseline = build_assembler_argv(
        concat_list, narration, output, total_duration_s=10.0,
    )
    regression = build_assembler_argv(
        concat_list, narration, output, total_duration_s=10.0,
        resolution=(1080, 1920),
        fps=30,
    )
    assert _filtergraph(baseline) == _filtergraph(regression)


def test_build_argv_libx264_codec_emits_crf_not_nvenc_cq(tmp_path):
    shots = _shot_paths(2, tmp_path)
    concat_list = tmp_path / "list.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"
    narration.write_bytes(b"fake")
    output = tmp_path / "out.mp4"

    argv = build_assembler_argv(
        concat_list,
        narration,
        output,
        total_duration_s=8.0,
        shot_paths=shots,
        crossfade_enabled=False,
        video_codec="libx264",
    )

    assert "libx264" in argv
    assert "h264_nvenc" not in argv
    assert "-crf" in argv
    assert "-cq" not in argv
