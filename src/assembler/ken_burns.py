"""Ken Burns motion builder — still image to shot mp4 (Pivot.7)."""

from __future__ import annotations

import colorsys
import shutil
from pathlib import Path

from PIL import Image


def dominant_color(image_path: Path) -> tuple[int, int, int]:
    """Sample the photo's dominant RGB via a small quantized resize."""
    with Image.open(image_path) as im:
        rgb = im.convert("RGB").resize((64, 64))
        paletted = rgb.quantize(colors=1, method=Image.Quantize.MEDIANCUT)
        palette = paletted.getpalette()
        if not palette:
            return (32, 32, 32)
        return (int(palette[0]), int(palette[1]), int(palette[2]))


def clamp_dark_for_subtitles(
    rgb: tuple[int, int, int],
    *,
    max_luma: int = 45,
    max_saturation: float = 0.35,
) -> tuple[int, int, int]:
    """Force RGB into a dark, desaturated band for subtitle contrast."""
    r, g, b = (c / 255.0 for c in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s = min(s, max_saturation)
    v = min(v, max_luma / 255.0)
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
    return (int(r2 * 255), int(g2 * 255), int(b2 * 255))


def _fitted_size(image_path: Path, width: int, height: int) -> tuple[int, int]:
    with Image.open(image_path) as im:
        iw, ih = im.size
    if iw <= 0 or ih <= 0:
        return (width, height)
    scale = min(width / iw, height / ih)
    fw = max(int(iw * scale), 2)
    fh = max(int(ih * scale), 2)
    # ffmpeg prefers even dimensions
    return (fw - fw % 2, fh - fh % 2)


def _rgb_hex(rgb: tuple[int, int, int]) -> str:
    return f"0x{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def build_ken_burns_argv(
    image_path: Path,
    dest: Path,
    *,
    duration_s: float = 4.0,
    resolution: tuple[int, int] = (1080, 1920),
    zoom_rate: float = 0.0015,
    fps: int = 30,
    nvenc_preset: str = "p5",
    nvenc_cq: int = 23,
    gradient_luma_max: int = 45,
    gradient_saturation_max: float = 0.35,
) -> list[str]:
    """Return ffmpeg argv to render a Ken Burns shot from a still. Pure — no ffmpeg invoked."""
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    width, height = resolution
    frames = max(int(duration_s * fps), 1)
    fg_w, fg_h = _fitted_size(image_path, width, height)

    base = dominant_color(image_path)
    bg_top = clamp_dark_for_subtitles(
        base,
        max_luma=gradient_luma_max,
        max_saturation=gradient_saturation_max,
    )
    bg_bottom = clamp_dark_for_subtitles(
        tuple(max(0, c - 18) for c in base),
        max_luma=min(gradient_luma_max + 12, 60),
        max_saturation=gradient_saturation_max,
    )

    zoompan = (
        f"zoompan=z='min(zoom+{zoom_rate},{zoom_rate}*100+1)':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={fg_w}x{fg_h}:fps={fps}"
    )
    filtergraph = (
        f"color=c={_rgb_hex(bg_top)}:s={width}x{height}:d={duration_s}[bg_a];"
        f"color=c={_rgb_hex(bg_bottom)}:s={width}x{height}:d={duration_s}[bg_b];"
        f"[bg_a][bg_b]blend=all_expr='A*(1-Y/H)+B*(Y/H)'[v_bg];"
        f"[0:v]scale={fg_w}:{fg_h}:force_original_aspect_ratio=decrease,"
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
