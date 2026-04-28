import math

import pytest

from src.discovery.virality import (
    compute_niche_median,
    score_virality,
)


def test_score_basic_ordering():
    """Higher views should score higher when other inputs match."""
    low = score_virality(views=1_000, age_hours=48, likes=10, comments=2, niche_median_views=10_000)
    high = score_virality(views=100_000, age_hours=48, likes=1_000, comments=200, niche_median_views=10_000)
    assert high > low > 0


def test_score_handles_zero_views():
    """0-view video must not raise; should score effectively 0 (well below threshold)."""
    s = score_virality(views=0, age_hours=24, likes=0, comments=0, niche_median_views=1000)
    assert s < 1e-3  # well below the 1.0 threshold; non-zero from the +1 floors


def test_score_handles_zero_niche_median():
    """0 niche median substituted with 1; no div-by-zero."""
    s = score_virality(views=10_000, age_hours=48, likes=100, comments=20, niche_median_views=0)
    assert s > 0


def test_score_handles_zero_age():
    """0 age clamped to 24h floor."""
    s_zero = score_virality(views=10_000, age_hours=0, likes=100, comments=20, niche_median_views=1000)
    s_24 = score_virality(views=10_000, age_hours=24, likes=100, comments=20, niche_median_views=1000)
    assert s_zero == s_24


def test_score_engagement_capped():
    """Engagement multiplier caps at 0.5+1.5=2.0 even with extreme like ratios."""
    extreme = score_virality(views=100, age_hours=24, likes=10_000, comments=10_000, niche_median_views=100)
    s_match_views_term = math.log10(100 / 24 + 1) * 2.0 * math.log10(100 / 100 + 1)
    assert extreme == pytest.approx(s_match_views_term, rel=1e-9)


def test_compute_niche_median_empty():
    assert compute_niche_median([]) == 1


def test_compute_niche_median_basic():
    assert compute_niche_median([100, 200, 300, 400, 500]) == 300
    assert compute_niche_median([1, 2, 3, 4]) == 2  # median of 2,3 -> 2.5 -> int truncated


def test_threshold_filtering():
    """Hand-picked tuple confirms the formula clears the configured 1.0 threshold."""
    # A "viral" Joe Rogan-style clip: 500k views in 48h, ~5% like rate, niche median 50k
    s = score_virality(views=500_000, age_hours=48, likes=25_000, comments=2_000, niche_median_views=50_000)
    assert s > 1.0
