"""ffmpeg argv builder for Pivot.6 assembly.

Pivot.6 assembly is fundamentally different from the old editor (sourced clips):
  - Input: N shot MP4s already in 1080x1920 native format (no blurred-bg)
  - Audio: external narration MP3 (no dialogue extraction from shots)
  - No subtitle burn (Slice 5 adds that)
  - Optional music bed duck/mix

Workflow:
  1. write_concat_list() -> shots_list.txt (ffmpeg concat format)
  2. build_assembler_argv() -> argv for ffmpeg subprocess

Video filtergraph:
  [0:v] concat N shots, fps=30 -> [v_out]

Audio filtergraph (no music):
  [1:a] loudnorm -> aresample -> [a]

Audio filtergraph (with music):
  [1:a] loudnorm -> aresample -> [a_voice]
  [2:a] aloop -> atrim -> asetpts -> volume -> aresample -> [a_music]
  [a_voice][a_music] amix -> [a]
"""

from __future__ import annotations

import shutil
from pathlib import Path


def write_concat_list(shot_paths: list[Path], dest: Path) -> Path:
    """Write an ffmpeg concat list file for the given shot paths. Returns dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"file '{p}'" for p in shot_paths]
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def build_assembler_argv(
    concat_list: Path,
    narration_path: Path,
    output_path: Path,
    total_duration_s: float,
    *,
    music_path: Path | None = None,
    ass_path: Path | None = None,
    music_volume_db: float = -15.0,
    loudness_target_lufs: float = -14.0,
    nvenc_preset: str = "p5",
    nvenc_cq: int = 23,
) -> list[str]:
    """Return ffmpeg argv for Pivot.6 assembly. No ffmpeg is invoked here."""
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    music_enabled = music_path is not None

    filtergraph = _build_filtergraph(
        total_duration_s=total_duration_s,
        music_enabled=music_enabled,
        music_volume_db=music_volume_db,
        loudness_target_lufs=loudness_target_lufs,
        ass_path=ass_path,
    )

    argv: list[str] = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        # Input 0: concat list of shot MP4s
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        # Input 1: narration MP3
        "-i", str(narration_path),
    ]

    if music_enabled:
        # Input 2: background music
        argv += ["-i", str(music_path)]

    argv += [
        "-filter_complex", filtergraph,
        "-map", "[v_out]",
        "-map", "[a]",
        "-c:v", "h264_nvenc",
        "-preset", nvenc_preset,
        "-cq", str(nvenc_cq),
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path),
    ]

    return argv


def _escape_ass_path(path: Path) -> str:
    """Escape a path for use in the libass filter argument (same rules as editor)."""
    s = str(path)
    s = s.replace("\\", "\\\\")
    s = s.replace(":", "\\:")
    s = s.replace(",", "\\,")
    s = s.replace("'", "\\'")
    return f"'{s}'"


def _build_filtergraph(
    *,
    total_duration_s: float,
    music_enabled: bool,
    music_volume_db: float,
    loudness_target_lufs: float,
    ass_path: Path | None = None,
) -> str:
    # Video: shots are already 1080x1920; lock fps, optionally burn subtitles.
    if ass_path is not None:
        video_chain = f"[0:v]fps=30,ass={_escape_ass_path(ass_path)}[v_out]"
    else:
        video_chain = "[0:v]fps=30[v_out]"

    # Narration audio chain: loudnorm -> resample.
    narration_filters = (
        f"loudnorm=I={loudness_target_lufs:g}:LRA=11:TP=-1.0,"
        "aresample=48000"
    )

    if music_enabled:
        audio_chain = (
            f"[1:a]{narration_filters}[a_voice];"
            f"[2:a]aloop=loop=-1:size=2147483647,"
            f"atrim=0:{total_duration_s:.3f},"
            f"asetpts=PTS-STARTPTS,"
            f"volume={music_volume_db:g}dB,"
            f"aresample=48000[a_music];"
            "[a_voice][a_music]amix=inputs=2:duration=first:normalize=0[a]"
        )
    else:
        audio_chain = f"[1:a]{narration_filters}[a]"

    return f"{video_chain};{audio_chain}"
