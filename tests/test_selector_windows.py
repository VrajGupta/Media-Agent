"""Window slicing: baseline + heatmap-centered + dedup."""

from __future__ import annotations

from src.selector.windows import (
    HeatMarker,
    Window,
    baseline_windows,
    build_windows,
    cap_candidates,
    heatmap_centered_windows,
)


def _seg(start: float, end: float, text: str = "x"):
    return {"start": start, "end": end, "text": text, "words": []}


# 10 segments × 10 s = 100 s of audio.
def _ten_seg_video():
    return [_seg(i * 10.0, (i + 1) * 10.0, f"seg{i}") for i in range(10)]


# ---- baseline_windows -------------------------------------------------------


def test_baseline_emits_30_to_60_windows():
    segments = _ten_seg_video()
    out = baseline_windows(segments, 30.0, 60.0)
    # Each emitted window is exactly 30s (3 segments) given the layout.
    assert len(out) == 3  # [0-30), [30-60), [60-90); 90-100 is too short.
    assert out[0] == (0.0, 30.0, 0, 2)
    assert out[1] == (30.0, 60.0, 3, 5)
    assert out[2] == (60.0, 90.0, 6, 8)


def test_baseline_short_video_emits_zero():
    """Total duration < min_seconds → no windows."""
    segments = [_seg(0.0, 10.0), _seg(10.0, 20.0)]  # 20s total
    assert baseline_windows(segments, 30.0, 60.0) == []


def test_baseline_empty_segments():
    assert baseline_windows([], 30.0, 60.0) == []


def test_baseline_exact_30s_boundary():
    """A single segment exactly at min_seconds should emit."""
    segments = [_seg(0.0, 30.0), _seg(30.0, 60.0)]
    out = baseline_windows(segments, 30.0, 60.0)
    assert out == [(0.0, 30.0, 0, 0), (30.0, 60.0, 1, 1)]


# ---- heatmap_centered_windows -----------------------------------------------


def test_heatmap_centered_one_marker_yields_one_window():
    segments = _ten_seg_video()
    markers = [HeatMarker(start_s=45.0, duration_s=5.0, intensity=0.95)]
    out = heatmap_centered_windows(segments, markers, 30.0, 60.0, top_k=5)
    assert len(out) == 1
    s, e, _, _ = out[0]
    # Window must be in [30, 60] duration.
    assert 30.0 <= (e - s) <= 60.0
    # Marker midpoint (47.5) falls inside the window.
    assert s <= 47.5 <= e


def test_heatmap_centered_picks_top_k_by_intensity():
    segments = _ten_seg_video()
    markers = [
        HeatMarker(10.0, 5.0, 0.1),
        HeatMarker(30.0, 5.0, 0.9),  # top
        HeatMarker(50.0, 5.0, 0.95),  # top
        HeatMarker(70.0, 5.0, 0.5),
        HeatMarker(90.0, 5.0, 0.3),
    ]
    out = heatmap_centered_windows(segments, markers, 30.0, 60.0, top_k=2)
    assert len(out) == 2


def test_heatmap_centered_no_markers_returns_empty():
    segments = _ten_seg_video()
    assert heatmap_centered_windows(segments, [], 30.0, 60.0) == []


# ---- build_windows: merge + dedup + candidate_ids ---------------------------


def test_build_windows_assigns_sequential_candidate_ids():
    segments = _ten_seg_video()
    out = build_windows(segments, markers=None, min_seconds=30.0, max_seconds=60.0)
    assert [w.candidate_id for w in out] == [f"c{i}" for i in range(len(out))]


def test_build_windows_dedup_prefers_heatmap_centered():
    """A baseline window and a heatmap-centered window with the same range
    should collapse to one Window with source='heatmap_centered'."""
    segments = _ten_seg_video()
    # Baseline at [0-30) is identical to heatmap-centered at marker midpoint=15.
    markers = [HeatMarker(start_s=14.0, duration_s=2.0, intensity=0.99)]
    out = build_windows(segments, markers=markers, min_seconds=30.0, max_seconds=60.0)
    # Find any window covering [0, 30].
    overlap = [w for w in out if abs(w.start_s - 0.0) <= 1.0 and abs(w.end_s - 30.0) <= 1.0]
    assert len(overlap) == 1
    assert overlap[0].source == "heatmap_centered"


def test_build_windows_marks_heatmap_peak_flag():
    segments = _ten_seg_video()
    markers = [HeatMarker(start_s=45.0, duration_s=5.0, intensity=0.99)]
    out = build_windows(segments, markers=markers, min_seconds=30.0, max_seconds=60.0)
    # The window covering 45-50 should have heatmap_peak=True.
    overlapping = [w for w in out if w.start_s <= 47.5 <= w.end_s]
    assert overlapping
    assert all(w.heatmap_peak for w in overlapping)


def test_build_windows_zero_when_video_too_short():
    segments = [_seg(0.0, 10.0)]
    out = build_windows(segments, markers=None, min_seconds=30.0, max_seconds=60.0)
    assert out == []


# ---- cap_candidates ---------------------------------------------------------


def _mk_window(idx: int, source: str = "baseline", heat: bool = False) -> Window:
    return Window(
        candidate_id=f"c{idx}",
        start_s=float(idx * 30),
        end_s=float(idx * 30 + 30),
        text=f"text {idx}",
        words=[],
        heatmap_peak=heat,
        source=source,
    )


def test_cap_no_op_when_under_limit():
    windows = [_mk_window(i) for i in range(10)]
    out = cap_candidates(windows, max_count=25)
    assert len(out) == 10
    assert [w.candidate_id for w in out] == [f"c{i}" for i in range(10)]


def test_cap_zero_or_negative_returns_renumbered_input():
    windows = [_mk_window(i) for i in range(5)]
    out = cap_candidates(windows, max_count=0)
    assert len(out) == 5


def test_cap_preserves_all_heatmap_centered():
    """Even if the cap is tight, all heatmap_centered windows survive."""
    heat_windows = [_mk_window(i, source="heatmap_centered", heat=True) for i in range(8)]
    base_windows = [_mk_window(i + 100, source="baseline") for i in range(50)]
    windows = heat_windows + base_windows
    out = cap_candidates(windows, max_count=10)
    # All 8 heatmap_centered must be in the output.
    sources = [w.source for w in out]
    assert sources.count("heatmap_centered") == 8
    assert len(out) == 10  # 8 heat + 2 baseline (filling remaining slots)


def test_cap_even_stride_baseline_when_no_heatmap():
    """Long video, no heatmap markers — baseline gets evenly sampled."""
    base_windows = [_mk_window(i, source="baseline") for i in range(100)]
    out = cap_candidates(base_windows, max_count=10)
    assert len(out) == 10
    # Even stride means starts should span the full range.
    starts = [w.start_s for w in out]
    assert starts[0] == 0.0  # first
    # Last picked is around index 90 (i=9, stride=10) — start_s = 90 * 30 = 2700
    assert starts[-1] >= 2700.0


def test_cap_renumbers_candidate_ids_contiguously():
    """LLM sees c0..c{N-1} regardless of source mix."""
    heat_windows = [_mk_window(i, source="heatmap_centered", heat=True) for i in range(3)]
    base_windows = [_mk_window(i + 100, source="baseline") for i in range(50)]
    windows = heat_windows + base_windows
    out = cap_candidates(windows, max_count=10)
    assert [w.candidate_id for w in out] == [f"c{i}" for i in range(10)]


def test_cap_long_video_268_windows_capped_to_25():
    """Regression: 268 windows on a 1.5h Joe Rogan video overwhelmed
    qwen2.5:3b's effective context. Verify the exact case is now capped."""
    base_windows = [_mk_window(i, source="baseline") for i in range(268)]
    out = cap_candidates(base_windows, max_count=25)
    assert len(out) == 25
    # IDs are contiguous c0..c24.
    assert [w.candidate_id for w in out] == [f"c{i}" for i in range(25)]
