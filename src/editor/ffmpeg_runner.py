"""ffmpeg invocation for the editor (Pivot.3 — full-screen blurred-bg).

Builds the argv list and the filtergraph string, then runs subprocess.
Never builds shell strings — argv is always a list[str] passed to
subprocess.run with shell=False. Critical on Windows where path separators
and quoting differ from POSIX.

Pivot.3 changes vs Phase 4 (split-screen + gameplay):
- Drops the second video input (gameplay).
- Filtergraph now: split source → blurred-bg + foreground 1080x608 → overlay
  centered → ASS karaoke → fps=30.
- Audio chain: optional aecho (cinematic reverb) on dialogue, optional
  amix with looped + trimmed background music underneath.
- Pre-render audio probe rejects clips with no audio stream (movie clips
  without audio aren't viable for this format).
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
    s = s.replace("\\", "\\\\")
    s = s.replace(":", "\\:")
    s = s.replace(",", "\\,")
    s = s.replace("'", "\\'")
    return f"'{s}'"


def build_filtergraph(
    *,
    ass_path: Path,
    duration_s: float,
    blurred_bg_sigma: int = 20,
    loudness_target_lufs: float = -14.0,
    music_enabled: bool = False,
    music_volume_db: float = -15.0,
    dialogue_reverb_enabled: bool = True,
    dialogue_reverb_aecho: str = "0.8:0.88:60:0.4",
) -> str:
    """Single-pass filtergraph for full-screen blurred-bg + ASS + audio mix.

    Video chain:
      [0:v] split -> [bg](scale-fill+crop+gblur) [fg](scale-fit 1080x608)
              -> overlay center -> fps=30 -> ass=...
    Audio chain (no music):
      [0:a] (aecho?) loudnorm aresample
    Audio chain (with music):
      [0:a] (aecho?) loudnorm aresample -> [a_voice]
      [1:a] aloop atrim volume aresample -> [a_music]
      [a_voice][a_music] amix=inputs=2:duration=first:normalize=0
    """
    ass_arg = escape_ass_filter_path(ass_path)

    # Video: split + blur + overlay + ass (single string with ; separators).
    video_chain = (
        # Duplicate the source video stream into background + foreground branches.
        "[0:v]split=2[v_src1][v_src2];"
        # Background: cover-fit then crop to 1080x1920 then gaussian-blur.
        f"[v_src1]scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,gblur=sigma={int(blurred_bg_sigma)}[v_bg];"
        # Foreground: fit-into 1080x608 (preserves the entire 16:9 frame).
        "[v_src2]scale=1080:608:force_original_aspect_ratio=decrease[v_fg];"
        # Overlay foreground centered on background, lock to 30fps.
        "[v_bg][v_fg]overlay=(W-w)/2:(H-h)/2,fps=30[v_comp];"
        # Burn ASS karaoke onto the composite.
        f"[v_comp]ass={ass_arg}[v_out]"
    )

    # Dialogue chain: optional reverb -> loudnorm -> resample.
    dialogue_filters: list[str] = []
    if dialogue_reverb_enabled and dialogue_reverb_aecho:
        dialogue_filters.append(f"aecho={dialogue_reverb_aecho}")
    dialogue_filters.append(
        f"loudnorm=I={loudness_target_lufs:g}:LRA=11:TP=-1.0"
    )
    dialogue_filters.append("aresample=48000")

    if music_enabled:
        # Music input is [1:a]; trim/loop to clip duration, then drop volume.
        # aloop with size=2147483647 effectively loops indefinitely; atrim
        # cuts to clip duration. volume converts dB → linear gain.
        music_chain = (
            f"[0:a]{','.join(dialogue_filters)}[a_voice];"
            f"[1:a]aloop=loop=-1:size=2147483647,atrim=0:{duration_s:.3f},"
            f"asetpts=PTS-STARTPTS,"
            f"volume={music_volume_db:g}dB,"
            f"aresample=48000[a_music];"
            f"[a_voice][a_music]amix=inputs=2:duration=first:normalize=0[a]"
        )
    else:
        # Dialogue-only: no music input, no amix.
        music_chain = f"[0:a]{','.join(dialogue_filters)}[a]"

    return f"{video_chain};{music_chain}"


def build_ffmpeg_argv(
    *,
    ffmpeg_bin: str,
    source_path: Path,
    source_start_s: float,
    duration_s: float,
    ass_path: Path,
    output_tmp_path: Path,
    music_path: Optional[Path] = None,
    music_offset_s: float = 0.0,
    nvenc_preset: str = "p5",
    nvenc_cq: int = 23,
    blurred_bg_sigma: int = 20,
    loudness_target_lufs: float = -14.0,
    music_volume_db: float = -15.0,
    dialogue_reverb_enabled: bool = True,
    dialogue_reverb_aecho: str = "0.8:0.88:60:0.4",
) -> list[str]:
    """Returns argv ready to feed subprocess.run(shell=False).

    -ss / -t are command args, NOT inside the filtergraph (libass and -ss
    inside filters do not compose well; argv-level seeking is the correct
    pattern).

    When music_path is None, only the source video input is added; the
    filtergraph collapses to dialogue-only audio.
    """
    music_enabled = music_path is not None
    filtergraph = build_filtergraph(
        ass_path=ass_path,
        duration_s=duration_s,
        blurred_bg_sigma=blurred_bg_sigma,
        loudness_target_lufs=loudness_target_lufs,
        music_enabled=music_enabled,
        music_volume_db=music_volume_db,
        dialogue_reverb_enabled=dialogue_reverb_enabled,
        dialogue_reverb_aecho=dialogue_reverb_aecho,
    )

    argv: list[str] = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        # Input 0: source video, with seek + duration.
        "-ss", f"{source_start_s:.3f}",
        "-t", f"{duration_s:.3f}",
        "-i", str(source_path),
    ]
    if music_enabled:
        # Input 1: music. Optional offset (so the same track played twice
        # sounds different). aloop in the filtergraph handles short tracks.
        argv += [
            "-ss", f"{music_offset_s:.3f}",
            "-i", str(music_path),
        ]
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
        str(output_tmp_path),
    ]
    return argv


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


def has_audio_stream(path: Path) -> bool:
    """Return True iff the source has at least one audio stream.

    Pivot.3 pre-render gate: movie clips without audio are not viable for
    this Shorts format (we'd be left with only the music bed, no dialogue
    to subtitle, no payoff). Reject upstream of the render.
    """
    bin_ = shutil.which("ffprobe") or "ffprobe"
    try:
        out = subprocess.check_output(
            [
                bin_,
                "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                str(path),
            ],
            text=True,
        ).strip()
        return bool(out)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.warning(f"ffprobe audio-stream check failed for {path}: {exc}")
        # Fail open: if the probe itself errors, assume audio exists and let
        # ffmpeg surface the real problem during render. Tests cover the
        # "no audio stream" rejection path with a synthetic path.
        return True
