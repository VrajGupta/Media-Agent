"""Shared clip-window word filtering for Phase 4.5 policy_gate and quality_screen.

The boundary rule mirrors src/subtitles/ass_writer.py:_filter_and_clip_words so
the karaoke timeline and the policy/quality text views see the same word set
for any given clip. Intersection with clipping (NOT midpoint inclusion):
include any word whose interval overlaps [start_s, end_s], then clip endpoints
to the boundary.
"""

from __future__ import annotations

from typing import Any


def words_in_clip_window(
    transcript_words: list[dict[str, Any]],
    start_s: float,
    end_s: float,
) -> list[dict[str, Any]]:
    """Words whose interval intersects [start_s, end_s].

    Returns dicts in original order with `start` and `end` clipped to the
    boundary. Words missing their text or collapsing to zero duration after
    clipping are dropped. The probability field (if present) is preserved
    so downstream confidence checks can read it without re-loading the
    transcript.
    """
    out: list[dict[str, Any]] = []
    for w in transcript_words:
        ws = float(w.get("start", 0.0))
        we = float(w.get("end", 0.0))
        if we <= start_s or ws >= end_s:
            continue
        ws = max(ws, start_s)
        we = min(we, end_s)
        if we <= ws:
            continue
        text = (w.get("word") or "").strip()
        if not text:
            continue
        clipped: dict[str, Any] = {"start": ws, "end": we, "word": text}
        if "probability" in w:
            clipped["probability"] = w["probability"]
        out.append(clipped)
    return out


def clip_text_from_words(words: list[dict[str, Any]]) -> str:
    """Join word.word with single spaces; collapse whitespace and newlines."""
    parts = []
    for w in words:
        token = (w.get("word") or "").strip()
        if token:
            parts.append(token)
    return " ".join(parts)
