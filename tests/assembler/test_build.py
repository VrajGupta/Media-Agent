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
