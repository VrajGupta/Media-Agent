"""Window slicing for Phase 3.

Two candidate sources, merged + deduped:
  1. Non-overlapping baseline: walk segments left-to-right, accumulate until
     duration in [min, max], emit, reset.
  2. Heatmap-centered: for each top-K marker, build a window centered on the
     marker midpoint, expand outward to the nearest segment boundaries until
     duration in [min, max]. Skip if no boundary set yields a valid duration.

LLM never sees raw timestamps — only candidate_id (e.g. "c0", "c1"). This
prevents the model from inventing windows that don't align with anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass
class HeatMarker:
    start_s: float
    duration_s: float
    intensity: float

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s

    @property
    def midpoint_s(self) -> float:
        return self.start_s + self.duration_s / 2.0


@dataclass
class Window:
    candidate_id: str
    start_s: float
    end_s: float
    text: str
    words: list[dict]
    heatmap_peak: bool
    source: str  # "baseline" | "heatmap_centered"

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def _segment_text(seg: dict) -> str:
    return (seg.get("text") or "").strip()


def _segment_words(seg: dict) -> list[dict]:
    return list(seg.get("words") or [])


def _slice_text_words(segments: list[dict], start_idx: int, end_idx: int) -> tuple[str, list[dict]]:
    """Concatenate text and flatten words across segments[start_idx:end_idx+1]."""
    parts: list[str] = []
    words: list[dict] = []
    for i in range(start_idx, end_idx + 1):
        seg = segments[i]
        t = _segment_text(seg)
        if t:
            parts.append(t)
        words.extend(_segment_words(seg))
    return " ".join(parts), words


def baseline_windows(
    segments: list[dict],
    min_seconds: float,
    max_seconds: float,
) -> list[tuple[float, float, int, int]]:
    """Non-overlapping accumulator. Returns list of (start_s, end_s, start_idx, end_idx)."""
    if not segments:
        return []
    out: list[tuple[float, float, int, int]] = []
    i = 0
    n = len(segments)
    while i < n:
        run_start = float(segments[i]["start"])
        j = i
        while j < n:
            run_end = float(segments[j]["end"])
            duration = run_end - run_start
            if duration >= min_seconds:
                if duration <= max_seconds:
                    out.append((run_start, run_end, i, j))
                    i = j + 1
                    break
                # Exceeded max without hitting min cleanly — emit if previous index
                # gave us something in range, else skip this start.
                if j > i:
                    prev_end = float(segments[j - 1]["end"])
                    prev_duration = prev_end - run_start
                    if min_seconds <= prev_duration <= max_seconds:
                        out.append((run_start, prev_end, i, j - 1))
                        i = j
                        break
                # No valid emit; advance start by one segment.
                i += 1
                break
            j += 1
        else:
            # Reached end of segments without satisfying min_seconds — done.
            break
    return out


def heatmap_centered_windows(
    segments: list[dict],
    markers: list[HeatMarker],
    min_seconds: float,
    max_seconds: float,
    top_k: int = 5,
) -> list[tuple[float, float, int, int]]:
    """For each top-K marker, build a window around its midpoint expanded to
    segment boundaries until duration ∈ [min, max]. Skip if no expansion
    achieves a valid duration."""
    if not segments or not markers:
        return []
    top = sorted(markers, key=lambda m: m.intensity, reverse=True)[:top_k]
    out: list[tuple[float, float, int, int]] = []
    n = len(segments)
    for marker in top:
        mid = marker.midpoint_s
        # Find the segment containing or closest-to mid.
        center_idx = 0
        for idx, seg in enumerate(segments):
            if float(seg["start"]) <= mid <= float(seg["end"]):
                center_idx = idx
                break
            if float(seg["start"]) > mid:
                center_idx = max(0, idx - 1)
                break
        else:
            center_idx = n - 1

        best: Optional[tuple[float, float, int, int]] = None
        # Expand symmetrically; prefer slightly larger over slightly smaller
        # if a valid window exists.
        for radius in range(0, n):
            lo = max(0, center_idx - radius)
            hi = min(n - 1, center_idx + radius)
            start_s = float(segments[lo]["start"])
            end_s = float(segments[hi]["end"])
            duration = end_s - start_s
            if duration > max_seconds:
                break
            if min_seconds <= duration <= max_seconds:
                best = (start_s, end_s, lo, hi)
                break
            if lo == 0 and hi == n - 1:
                break
        if best is not None:
            out.append(best)
    return out


def _overlaps_marker(start_s: float, end_s: float, markers: list[HeatMarker], top_k: int = 5) -> bool:
    if not markers:
        return False
    top = sorted(markers, key=lambda m: m.intensity, reverse=True)[:top_k]
    for m in top:
        if not (end_s < m.start_s or start_s > m.end_s):
            return True
    return False


def build_windows(
    segments: list[dict],
    markers: Optional[list[HeatMarker]],
    min_seconds: float,
    max_seconds: float,
    top_k: int = 5,
    dedup_seconds: float = 1.0,
) -> list[Window]:
    """Merge baseline + heatmap-centered candidates, dedup, assign candidate_ids.

    Dedup rule: two windows whose (start_s, end_s) are within `dedup_seconds`
    of each other collapse; heatmap_centered wins over baseline.
    """
    markers = markers or []
    base = [(s, e, si, ei, "baseline") for (s, e, si, ei) in baseline_windows(segments, min_seconds, max_seconds)]
    heat = [(s, e, si, ei, "heatmap_centered") for (s, e, si, ei) in heatmap_centered_windows(segments, markers, min_seconds, max_seconds, top_k)]

    # Heatmap candidates listed first so they win on collision via _is_dup() check.
    candidates = heat + base
    kept: list[tuple[float, float, int, int, str]] = []
    for cand in candidates:
        s, e, *_ = cand
        is_dup = any(
            abs(s - ks) <= dedup_seconds and abs(e - ke) <= dedup_seconds
            for (ks, ke, *_rest) in kept
        )
        if not is_dup:
            kept.append(cand)

    # Stable order by start_s for deterministic candidate_ids across runs.
    kept.sort(key=lambda x: (x[0], x[1]))

    out: list[Window] = []
    for idx, (s, e, si, ei, source) in enumerate(kept):
        text, words = _slice_text_words(segments, si, ei)
        out.append(Window(
            candidate_id=f"c{idx}",
            start_s=s,
            end_s=e,
            text=text,
            words=words,
            heatmap_peak=_overlaps_marker(s, e, markers, top_k),
            source=source,
        ))
    return out
