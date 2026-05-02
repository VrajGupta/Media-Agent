"""Perceptual hash + chromaprint dedup (Phase 4.5).

pHash is the only reject signal in v1. Audio fingerprints are captured to
dup_hashes.audio_fp for a Phase 7 follow-up, but they don't gate rejection
because chromaprint prefix-match is brittle across re-encodes.

Frame timestamps at 10/30/50/70/90% of clip duration — avoids black /
boundary frames at exact endpoints.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger

# Lazy imports so unit tests can patch them without paying the price.
import imagehash
from PIL import Image

FRAME_PERCENTS = (0.10, 0.30, 0.50, 0.70, 0.90)


@dataclass
class DedupSignals:
    phashes: list[str]
    audio_fp: Optional[str]


@dataclass
class DedupMatch:
    matching_clip_id: str
    hamming_distance: int


def _extract_frame_phash(video_path: Path, timestamp_s: float, work_dir: Path) -> Optional[str]:
    """Pull a single frame at timestamp_s, hash it, return hex pHash."""
    bin_ = shutil.which("ffmpeg") or "ffmpeg"
    out_png = work_dir / f"frame_{int(timestamp_s * 1000)}.png"
    argv = [
        bin_, "-hide_banner", "-nostats", "-y",
        "-ss", f"{timestamp_s:.3f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(out_png),
    ]
    try:
        result = subprocess.run(argv, shell=False, capture_output=True, timeout=60)
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning(f"frame extract subprocess error at t={timestamp_s}: {exc}")
        return None
    if result.returncode != 0 or not out_png.exists() or out_png.stat().st_size == 0:
        return None
    try:
        with Image.open(out_png) as img:
            return str(imagehash.phash(img))
    except (OSError, ValueError) as exc:
        logger.warning(f"phash compute error at t={timestamp_s}: {exc}")
        return None
    finally:
        try:
            out_png.unlink()
        except OSError:
            pass


def _compute_audio_fingerprint(video_path: Path) -> Optional[str]:
    """Return the chromaprint fingerprint string, or None on failure.

    Uses pyacoustid.fingerprint_file which shells to fpcalc internally.
    """
    try:
        import acoustid
    except ImportError as exc:
        logger.warning(f"pyacoustid unavailable: {exc}")
        return None
    try:
        _duration, fp = acoustid.fingerprint_file(str(video_path))
    except Exception as exc:  # acoustid raises a custom hierarchy; catch broadly.
        logger.warning(f"chromaprint fingerprint error: {exc}")
        return None
    if isinstance(fp, bytes):
        try:
            fp = fp.decode("ascii")
        except UnicodeDecodeError:
            return None
    return str(fp) if fp else None


def compute_signals(video_path: Path, duration_s: float) -> DedupSignals:
    """Extract 5 frame phashes (deduplicated) + audio fingerprint.

    Caller must have already verified `duration_s > 0` (Phase 4.5 enforces
    this via the foundational duration probe).
    """
    phashes_seen: list[str] = []
    seen_set: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="qs_dedup_") as tmpdir:
        work = Path(tmpdir)
        for pct in FRAME_PERCENTS:
            t = pct * duration_s
            ph = _extract_frame_phash(video_path, t, work)
            if ph and ph not in seen_set:
                seen_set.add(ph)
                phashes_seen.append(ph)

    audio_fp = _compute_audio_fingerprint(video_path)
    return DedupSignals(phashes=phashes_seen, audio_fp=audio_fp)


def find_phash_match(
    candidate_phashes: list[str],
    stored_rows: list[dict],
    *,
    min_hamming: int,
) -> Optional[DedupMatch]:
    """Return the first (clip_id, distance) where any candidate phash has
    Hamming distance < min_hamming to any stored phash. None if all candidates
    are sufficiently distinct from every stored row.

    `stored_rows` is a list of {clip_id, phash, audio_fp} (sqlite3.Row works).
    """
    if not candidate_phashes or not stored_rows:
        return None
    candidate_hashes = []
    for h in candidate_phashes:
        try:
            candidate_hashes.append(imagehash.hex_to_hash(h))
        except ValueError:
            continue
    if not candidate_hashes:
        return None

    best: Optional[DedupMatch] = None
    for row in stored_rows:
        try:
            stored_phash = imagehash.hex_to_hash(row["phash"])
        except (KeyError, ValueError, TypeError):
            continue
        for ch in candidate_hashes:
            dist = ch - stored_phash
            if dist < min_hamming:
                if best is None or dist < best.hamming_distance:
                    best = DedupMatch(
                        matching_clip_id=row["clip_id"],
                        hamming_distance=dist,
                    )
    return best
