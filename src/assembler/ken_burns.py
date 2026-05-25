"""Ken Burns motion builder — still image to shot mp4 (Pivot.7)."""

from __future__ import annotations

import shutil
from pathlib import Path


def build_ken_burns_argv(
    image_path: Path,
    dest: Path,
    *,
    duration_s: float = 4.0,
    resolution: tuple[int, int] = (1080, 1920),
    zoom_rate: float = 0.0015,
    blurred_bg_sigma: int = 20,
    fps: int = 30,
    nvenc_preset: str = "p5",
    nvenc_cq: int = 23,
) -> list[str]:
    """Return ffmpeg argv to render a Ken Burns shot from a still. Pure — no ffmpeg invoked."""
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    width, height = resolution
    frames = max(int(duration_s * fps), 1)
    zoompan = (
        f"zoompan=z='min(zoom+{zoom_rate},{zoom_rate}*100+1)':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={width}x{height}:fps={fps}"
    )
    filtergraph = (
        f"[0:v]split=2[v_src1][v_src2];"
        f"[v_src1]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},gblur=sigma={int(blurred_bg_sigma)}[v_bg];"
        f"[v_src2]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"{zoompan}[v_fg];"
        f"[v_bg][v_fg]overlay=(W-w)/2:(H-h)/2,fps={fps}[v_out]"
    )
    return [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-loop", "1",
        "-i", str(image_path),
        "-filter_complex", filtergraph,
        "-map", "[v_out]",
        "-t", str(duration_s),
        "-c:v", "h264_nvenc",
        "-preset", nvenc_preset,
        "-cq", str(nvenc_cq),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(dest),
    ]
