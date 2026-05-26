"""ffmpeg argv builder for Pivot.6 assembly.

Pivot.6 assembly is fundamentally different from the old editor (sourced clips):
  - Input: N shot MP4s (heterogeneous resolution/fps in Pivot.7 hybrid)
  - Audio: external narration MP3 (no dialogue extraction from shots)
  - Optional music bed duck/mix
  - Per-input shot normalization before stitch (ADR-0002)

Workflow:
  1. write_concat_list() -> shots_list.txt (legacy single-input concat demuxer)
  2. build_assembler_argv() -> argv for ffmpeg subprocess

Video filtergraph (multi-shot):
  normalize each [i:v] -> [vn{i}], then xfade or concat filter -> [v_out]
"""

from __future__ import annotations

import shutil
from pathlib import Path

from src.assembler.normalize import normalize_input_chain


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
    libx264_preset: str = "medium",
    libx264_crf: int = 23,
    shot_paths: list[Path] | None = None,
    crossfade_enabled: bool = False,
    crossfade_duration_s: float = 0.25,
    shot_durations_s: list[float] | None = None,
    resolution: tuple[int, int] = (1080, 1920),
    fps: int = 30,
    video_codec: str = "h264_nvenc",
) -> list[str]:
    """Return ffmpeg argv for Pivot.6/7 assembly. No ffmpeg is invoked here."""
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    music_enabled = music_path is not None
    multi_shot = bool(shot_paths and len(shot_paths) > 1)
    use_crossfade = crossfade_enabled and multi_shot
    width, height = resolution

    filtergraph = _build_filtergraph(
        total_duration_s=total_duration_s,
        music_enabled=music_enabled,
        music_volume_db=music_volume_db,
        loudness_target_lufs=loudness_target_lufs,
        ass_path=ass_path,
        shot_paths=shot_paths if multi_shot else None,
        crossfade_enabled=use_crossfade,
        crossfade_duration_s=crossfade_duration_s,
        shot_durations_s=shot_durations_s,
        width=width,
        height=height,
        fps=fps,
    )

    argv: list[str] = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
    ]

    if multi_shot:
        for shot in shot_paths:
            argv += ["-i", str(shot)]
    else:
        argv += [
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
        ]

    argv += ["-i", str(narration_path)]

    if music_enabled:
        argv += ["-i", str(music_path)]

    argv += [
        "-filter_complex", filtergraph,
        "-map", "[v_out]",
        "-map", "[a]",
    ]

    if video_codec == "h264_nvenc":
        argv += [
            "-c:v", "h264_nvenc",
            "-preset", nvenc_preset,
            "-cq", str(nvenc_cq),
        ]
    else:
        argv += [
            "-c:v", video_codec,
            "-preset", libx264_preset,
            "-crf", str(libx264_crf),
        ]

    argv += [
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


def _finalize_video_chain(comp_label: str, *, fps: int, ass_path: Path | None) -> str:
    if ass_path is not None:
        return f"[{comp_label}]fps={fps},ass={_escape_ass_path(ass_path)}[v_out]"
    return f"[{comp_label}]fps={fps}[v_out]"


def _build_filtergraph(
    *,
    total_duration_s: float,
    music_enabled: bool,
    music_volume_db: float,
    loudness_target_lufs: float,
    ass_path: Path | None = None,
    shot_paths: list[Path] | None = None,
    crossfade_enabled: bool = False,
    crossfade_duration_s: float = 0.25,
    shot_durations_s: list[float] | None = None,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> str:
    if shot_paths and len(shot_paths) > 1:
        if crossfade_enabled:
            durations = shot_durations_s or [4.0] * len(shot_paths)
            video_chain = _build_crossfade_video_chain(
                len(shot_paths),
                durations,
                crossfade_duration_s,
                width=width,
                height=height,
                fps=fps,
                ass_path=ass_path,
            )
        else:
            video_chain = _build_concat_filter_video_chain(
                len(shot_paths),
                width=width,
                height=height,
                fps=fps,
                ass_path=ass_path,
            )
    elif ass_path is not None:
        video_chain = f"[0:v]fps={fps},ass={_escape_ass_path(ass_path)}[v_out]"
    else:
        video_chain = f"[0:v]fps={fps}[v_out]"

    narr_input = len(shot_paths) if shot_paths else 1
    music_input = narr_input + 1

    narration_filters = (
        f"loudnorm=I={loudness_target_lufs:g}:LRA=11:TP=-1.0,"
        "aresample=48000"
    )

    if music_enabled:
        audio_chain = (
            f"[{narr_input}:a]{narration_filters}[a_voice];"
            f"[{music_input}:a]aloop=loop=-1:size=2147483647,"
            f"atrim=0:{total_duration_s:.3f},"
            f"asetpts=PTS-STARTPTS,"
            f"volume={music_volume_db:g}dB,"
            f"aresample=48000[a_music];"
            "[a_voice][a_music]amix=inputs=2:duration=first:normalize=0[a]"
        )
    else:
        audio_chain = f"[{narr_input}:a]{narration_filters}[a]"

    return f"{video_chain};{audio_chain}"


def _build_concat_filter_video_chain(
    n_shots: int,
    *,
    width: int,
    height: int,
    fps: int,
    ass_path: Path | None = None,
) -> str:
    norm_chains = [
        normalize_input_chain(i, width=width, height=height, fps=fps)
        for i in range(n_shots)
    ]
    concat_inputs = "".join(f"[vn{i}]" for i in range(n_shots))
    chain = (
        f"{';'.join(norm_chains)};"
        f"{concat_inputs}concat=n={n_shots}:v=1:a=0[v_comp]"
    )
    return f"{chain};{_finalize_video_chain('v_comp', fps=fps, ass_path=ass_path)}"


def _build_crossfade_video_chain(
    n_shots: int,
    durations: list[float],
    crossfade_s: float,
    *,
    width: int,
    height: int,
    fps: int,
    ass_path: Path | None = None,
) -> str:
    """Build xfade chain for N normalized shot inputs."""
    if n_shots < 2:
        raise ValueError("crossfade requires at least 2 shots")

    norm_chains = [
        normalize_input_chain(i, width=width, height=height, fps=fps)
        for i in range(n_shots)
    ]
    parts: list[str] = list(norm_chains)
    label_in = "[vn0]"
    elapsed = durations[0]
    for i in range(1, n_shots):
        label_out = f"[vx{i}]" if i < n_shots - 1 else "[v_comp]"
        offset = max(elapsed - crossfade_s, 0.0)
        parts.append(
            f"{label_in}[vn{i}]xfade=transition=fade:duration={crossfade_s:g}:offset={offset:g}{label_out}"
        )
        label_in = label_out
        elapsed += durations[i] - crossfade_s
    chain = ";".join(parts)
    return f"{chain};{_finalize_video_chain('v_comp', fps=fps, ass_path=ass_path)}"
