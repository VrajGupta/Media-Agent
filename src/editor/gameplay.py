"""Gameplay rotation: pick next file + offset from gameplay_pointer/cursor.

Two-step protocol per clip render:
  1. reserve(): read pointer + cursor; return ReservedSegment without writing.
  2. (after render success) commit_advance(): single short transaction
     advancing pointer + cursor + clip status.

The reservation is purely a read; if rendering fails the next clip retries
with the same (file, offset). No double-consumption.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger

from src.editor import ffmpeg_runner
from src.state import Repository

WRAP_SAFETY_MARGIN_S = 1.0


@dataclass
class ReservedSegment:
    file_name: str            # the path string used as the gameplay_cursor PK
    file_path: Path           # absolute or project-relative
    offset_s: float           # clip start within the file
    duration_s: float         # clip duration (== clip.end_s - clip.start_s)
    file_duration_s: float    # full file duration (probed once, cached after)
    next_pointer_index: int   # what gameplay_pointer.next_index becomes after render


def _resolve_pool_path(repo_root: Path, rel_or_abs: str) -> Path:
    p = Path(rel_or_abs)
    return p if p.is_absolute() else (repo_root / p)


def _ensure_file_duration(
    repo: Repository,
    file_name: str,
    file_path: Path,
    cached_duration: Optional[float],
) -> Optional[float]:
    """Return file_duration_s, probing via ffprobe if not cached.

    The probe result is NOT written here — that happens inside the post-render
    commit transaction so we don't write to the DB outside reservation/commit.
    """
    if cached_duration is not None and cached_duration > 0:
        return cached_duration
    duration = ffmpeg_runner.ffprobe_duration_seconds(file_path)
    if duration is None or duration <= 0:
        logger.warning(f"could not probe duration for {file_path}")
        return None
    return duration


def reserve_next_segment(
    repo: Repository,
    repo_root: Path,
    gameplay_pool: list[str],
    clip_duration_s: float,
) -> Optional[ReservedSegment]:
    """Pick the next file + offset for a clip of `clip_duration_s` seconds.

    Returns None if the pool is empty or the chosen file's duration cannot be
    probed (the caller should treat this as a render failure and skip).
    """
    if not gameplay_pool:
        logger.error("gameplay_pool is empty in config")
        return None

    pointer_idx = repo.read_gameplay_pointer() % len(gameplay_pool)
    rel_path = gameplay_pool[pointer_idx]
    file_path = _resolve_pool_path(repo_root, rel_path)
    file_name = rel_path  # PK in gameplay_cursor

    if not file_path.exists():
        logger.error(f"gameplay file missing: {file_path}")
        return None

    last_offset_s, cached_duration = repo.read_gameplay_cursor(file_name)
    file_duration_s = _ensure_file_duration(repo, file_name, file_path, cached_duration)
    if file_duration_s is None:
        return None

    # Wrap if this clip would overrun the file (with a 1s safety margin).
    if last_offset_s + clip_duration_s + WRAP_SAFETY_MARGIN_S > file_duration_s:
        last_offset_s = 0.0

    next_pointer_index = (pointer_idx + 1) % len(gameplay_pool)
    return ReservedSegment(
        file_name=file_name,
        file_path=file_path,
        offset_s=last_offset_s,
        duration_s=clip_duration_s,
        file_duration_s=file_duration_s,
        next_pointer_index=next_pointer_index,
    )


def commit_advance(
    repo: Repository,
    reservation: ReservedSegment,
) -> None:
    """Persist pointer + cursor advancement for a successful render.

    Caller MUST be inside repo.tx() so this update commits atomically with
    the clip status flip.
    """
    new_offset = reservation.offset_s + reservation.duration_s
    if new_offset + WRAP_SAFETY_MARGIN_S > reservation.file_duration_s:
        new_offset = 0.0
    repo.advance_gameplay_state(
        file_name=reservation.file_name,
        new_offset_s=new_offset,
        file_duration_s=reservation.file_duration_s,
        new_pointer_index=reservation.next_pointer_index,
    )
