"""ffmpeg invocation for Phase 4 vertical render.

Builds the argv list and the filtergraph string, then runs subprocess.
Never builds shell strings — argv is always a list[str] passed to
subprocess.run with shell=False. Critical on Windows where path separators
and quoting differ from POSIX.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger


@dataclass
class FfmpegResult:
    returncode: int
    stdout: str
    stderr: str
    output_size_bytes: int


def escape_ass_filter_path(path: str | Path) -> str:
    r"""Escape a filesystem path for use as the libass `ass=` filter argument.

    libass parses the filter argument with its own quoting rules. On Windows
    we must escape the drive colon, backslashes, commas, and apostrophes;
    then wrap the whole thing in single quotes.

    Examples:
      C:\\Users\\foo\\bar.ass  -> 'C\\:\\\\Users\\\\foo\\\\bar.ass'
      /tmp/x.ass               -> '/tmp/x.ass'

    Reference: https://ffmpeg.org/ffmpeg-filters.html#Notes-on-filtergraph-escaping
    """
    s = str(path)
    # Inside single quotes, backslashes need doubling (then libass un-doubles them).
    s = s.replace("\\", "\\\\")
    # Colon (drive letter) is the filter argument separator: escape it.
    s = s.replace(":", "\\:")
    # Commas separate filter chain items.
    s = s.replace(",", "\\,")
    # Apostrophe ends the single-quoted region; escape via the magic
    # close-quote / escaped-quote / re-open trick.
    s = s.replace("'", "\\'")
    return f"'{s}'"


def build_filtergraph(ass_path: Path, loudness_target_lufs: float = -14.0) -> str:
    """Single-pass filtergraph: top + bottom panes, vstack, ASS overlay,
    loudnorm on source audio. Gameplay audio is dropped (only [0:a] mapped).
    """
    ass_arg = escape_ass_filter_path(ass_path)
    return (
        # Top pane: source video, scale-fill 1080x960, center-crop.
        "[0:v]scale=1080:960:force_original_aspect_ratio=increase,"
        "crop=1080:960[top];"
        # Bottom pane: gameplay, same scale-fill + crop.
        "[1:v]scale=1080:960:force_original_aspect_ratio=increase,"
        "crop=1080:960[bot];"
        # Stack to 1080x1920 at 30fps.
        "[top][bot]vstack=inputs=2,fps=30[v];"
        # Burn ASS karaoke onto the stacked video.
        f"[v]ass={ass_arg}[vsub];"
        # Loudnorm only the source audio; resample to 48kHz for AAC mux.
        f"[0:a]loudnorm=I={loudness_target_lufs:g}:LRA=11:TP=-1.0,"
        "aresample=48000[a]"
    )


def build_ffmpeg_argv(
    *,
    ffmpeg_bin: str,
    source_path: Path,
    source_start_s: float,
    duration_s: float,
    gameplay_path: Path,
    gameplay_offset_s: float,
    ass_path: Path,
    output_tmp_path: Path,
    nvenc_preset: str = "p5",
    nvenc_cq: int = 23,
    loudness_target_lufs: float = -14.0,
) -> list[str]:
    """Returns argv ready to feed subprocess.run(shell=False).

    -ss / -t are command args, NOT inside the filtergraph (libass and -ss
    inside filters do not compose well; argv-level seeking is the correct
    pattern).
    """
    filtergraph = build_filtergraph(ass_path, loudness_target_lufs)
    return [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        # Input 0: source video, with seek + duration.
        "-ss", f"{source_start_s:.3f}",
        "-t", f"{duration_s:.3f}",
        "-i", str(source_path),
        # Input 1: gameplay loop, with seek + duration.
        "-ss", f"{gameplay_offset_s:.3f}",
        "-t", f"{duration_s:.3f}",
        "-i", str(gameplay_path),
        "-filter_complex", filtergraph,
        "-map", "[vsub]",
        "-map", "[a]",
        "-c:v", "h264_nvenc",
        "-preset", nvenc_preset,
        "-cq", str(nvenc_cq),
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_tmp_path),
    ]


def run_ffmpeg(argv: list[str], output_tmp_path: Path) -> FfmpegResult:
    """Invoke ffmpeg, capture output, return (returncode, stdout, stderr, size)."""
    logger.debug(f"ffmpeg argv: {argv}")
    try:
        proc = subprocess.run(
            argv,
            shell=False,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        logger.error(f"ffmpeg binary not found: {exc}")
        return FfmpegResult(returncode=127, stdout="", stderr=str(exc), output_size_bytes=0)

    size = output_tmp_path.stat().st_size if output_tmp_path.exists() else 0
    return FfmpegResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        output_size_bytes=size,
    )


def ffprobe_duration_seconds(path: Path) -> Optional[float]:
    """Return duration in seconds via `ffprobe -show_entries format=duration`,
    or None on failure. Mirrors src/downloader/ytdlp_runner.py:_ffprobe_height.
    """
    bin_ = shutil.which("ffprobe") or "ffprobe"
    try:
        out = subprocess.check_output(
            [
                bin_,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                str(path),
            ],
            text=True,
        ).strip()
        return float(out) if out else None
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as exc:
        logger.warning(f"ffprobe duration failed for {path}: {exc}")
        return None
