"""Final-duration check (Phase 4.5).

Reuses src/editor/ffmpeg_runner.py:ffprobe_duration_seconds. The probe is
declared foundational by the runner: a probe failure returns None and the
runner aborts the screen with error_probe (no other checks run).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.editor.ffmpeg_runner import ffprobe_duration_seconds

CLIP_MIN_SECONDS = 25.0
CLIP_MAX_SECONDS = 65.0


def probe_duration(path: Path) -> Optional[float]:
    """Returns probed duration in seconds, or None on probe failure."""
    return ffprobe_duration_seconds(path)


def passes_duration(
    duration_s: float,
    *,
    min_s: float = CLIP_MIN_SECONDS,
    max_s: float = CLIP_MAX_SECONDS,
) -> tuple[bool, float]:
    """In-range check. Caller computes duration via probe_duration first."""
    return (min_s <= duration_s <= max_s, duration_s)
