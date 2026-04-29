"""yt-dlp wrappers: probe (no download) and download_one (single-video fetch).

The probe pass exists so we can reject videos lacking a >=720p stream
*without* burning bandwidth. The format selector is strict band-only;
no sub-720p fallback.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import yt_dlp
from loguru import logger


def _video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def format_selector(min_height: int, max_height: int) -> str:
    """Strict band — no sub-floor fallback.

    Format: `bv*[height>=720][height<=1080]+ba/b[height>=720][height<=1080]`
    """
    band = f"[height>={min_height}][height<={max_height}]"
    return f"bv*{band}+ba/b{band}"


@dataclass
class ProbeOutcome:
    available_height: int | None  # None means no in-band format exists
    filesize_approx_bytes: int | None
    error: str | None


@dataclass
class DownloadOutcome:
    path: Path
    height: int | None
    filesize_bytes: int
    status: str  # 'ok' | 'rejected_format' | 'error'
    error_message: str | None


def probe(video_id: str, min_height: int, max_height: int) -> ProbeOutcome:
    """Inspect available formats without downloading."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(_video_url(video_id), download=False)
    except yt_dlp.utils.DownloadError as e:
        return ProbeOutcome(None, None, str(e))
    except Exception as e:  # network/parse layer
        return ProbeOutcome(None, None, f"{type(e).__name__}: {e}")

    formats = info.get("formats") or []
    in_band_video = [
        f for f in formats
        if f.get("vcodec") not in (None, "none")
        and f.get("height") is not None
        and min_height <= f["height"] <= max_height
    ]
    if not in_band_video:
        return ProbeOutcome(None, None, None)

    # Pick the highest-resolution in-band video format as the representative.
    best = max(in_band_video, key=lambda f: (f["height"], f.get("tbr") or 0))
    video_size = best.get("filesize") or best.get("filesize_approx")

    # Best audio (any) — videos.list doesn't tell us audio formats, so just
    # find the largest audio-only candidate, fall back to None.
    audio_only = [
        f for f in formats
        if f.get("vcodec") in (None, "none")
        and f.get("acodec") not in (None, "none")
    ]
    audio_size = None
    if audio_only:
        best_audio = max(
            audio_only, key=lambda f: f.get("filesize") or f.get("filesize_approx") or 0
        )
        audio_size = best_audio.get("filesize") or best_audio.get("filesize_approx")

    total = None
    if video_size is not None:
        total = video_size + (audio_size or 0)
    return ProbeOutcome(best["height"], total, None)


def _ffprobe_height(path: Path) -> int | None:
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=height",
                "-of", "csv=p=0",
                str(path),
            ],
            text=True,
        ).strip()
        return int(out) if out else None
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return None


def _resolved_height(info_dict: dict, dest_path: Path) -> int | None:
    """Authoritative final-stream height, with three fallbacks."""
    requested = info_dict.get("requested_downloads") or []
    if requested:
        h = requested[0].get("height")
        if h is not None:
            return int(h)
    h = info_dict.get("height")
    if h is not None:
        return int(h)
    if dest_path.exists():
        return _ffprobe_height(dest_path)
    return None


def cleanup_partial(dest_path: Path) -> int:
    """Remove yt-dlp sidecars (*.part, *.ytdl, *.f<id>.*, *.info.json, *.webm).

    Preserves dest_path itself. Returns the number of files unlinked.
    """
    if not dest_path.parent.exists():
        return 0
    count = 0
    for sibling in dest_path.parent.glob(f"{dest_path.stem}.*"):
        if sibling == dest_path:
            continue
        try:
            sibling.unlink()
            count += 1
        except OSError as e:
            logger.warning(f"cleanup_partial: failed to remove {sibling}: {e}")
    return count


def download_one(
    video_id: str,
    dest_path: Path,
    *,
    min_height: int,
    max_height: int,
) -> DownloadOutcome:
    """Fetch a single video to dest_path. Caller checks idempotency before calling."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    outtmpl = str(dest_path.with_suffix(".%(ext)s"))

    opts = {
        "quiet": True,
        "no_warnings": False,
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "format": format_selector(min_height, max_height),
        "noplaylist": True,
        "restrictfilenames": True,
        "retries": 3,
        "fragment_retries": 3,
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(_video_url(video_id), download=True)
    except yt_dlp.utils.DownloadError as e:
        cleanup_partial(dest_path)
        if dest_path.exists():
            try:
                dest_path.unlink()
            except OSError:
                pass
        return DownloadOutcome(
            path=dest_path, height=None, filesize_bytes=0,
            status="error", error_message=str(e),
        )
    except Exception as e:
        cleanup_partial(dest_path)
        return DownloadOutcome(
            path=dest_path, height=None, filesize_bytes=0,
            status="error", error_message=f"{type(e).__name__}: {e}",
        )

    if not dest_path.exists():
        # yt-dlp may have written something other than .mp4 if merge_output_format failed.
        cleanup_partial(dest_path)
        return DownloadOutcome(
            path=dest_path, height=None, filesize_bytes=0,
            status="error", error_message="output mp4 not produced",
        )

    height = _resolved_height(info, dest_path)
    if height is None or height < min_height:
        cleanup_partial(dest_path)
        try:
            dest_path.unlink()
        except OSError:
            pass
        return DownloadOutcome(
            path=dest_path, height=height, filesize_bytes=0,
            status="rejected_format",
            error_message=f"resolved height {height} below floor {min_height}",
        )

    filesize = dest_path.stat().st_size
    cleanup_partial(dest_path)
    return DownloadOutcome(
        path=dest_path, height=height, filesize_bytes=filesize,
        status="ok", error_message=None,
    )
