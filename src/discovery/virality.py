"""Pure-function helpers for the discovery stage.

The virality formula matches executive_plan.md §5.1 exactly:

    recency_factor   = views / max(age_hours, 24)
    engagement_rate  = (likes + 4*comments) / max(views, 1)
    niche_normalized = views / max(niche_median_views, 1)
    virality_score   = log10(recency_factor + 1)
                     * (0.5 + min(engagement_rate * 50, 1.5))
                     * log10(niche_normalized + 1)
"""

from __future__ import annotations

import math
import re
import statistics
from datetime import datetime, timezone
from typing import Iterable

_ISO_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)


def parse_iso8601_duration(s: str) -> int:
    """Parse a YouTube ISO 8601 duration like 'PT1H2M3S' into seconds.

    Handles missing components ('PT30S', 'PT1M', 'PT1H'). Returns 0 for empty
    or unparseable input — discovery treats 0-duration videos as failing the
    min_source_duration_seconds filter, which is the right outcome.
    """
    if not s:
        return 0
    m = _ISO_DURATION.match(s)
    if not m:
        return 0
    days = int(m.group("days") or 0)
    hours = int(m.group("hours") or 0)
    minutes = int(m.group("minutes") or 0)
    seconds = int(m.group("seconds") or 0)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def compute_age_hours(published_at_iso: str, now_utc: datetime) -> float:
    """Hours between `published_at_iso` (RFC 3339 / ISO 8601 with 'Z') and now."""
    s = published_at_iso.replace("Z", "+00:00")
    published = datetime.fromisoformat(s)
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    delta = now_utc - published
    return max(delta.total_seconds() / 3600.0, 0.0)


def score_virality(
    views: int,
    age_hours: float,
    likes: int,
    comments: int,
    niche_median_views: int,
) -> float:
    """Locked formula from executive_plan.md §5.1.

    Defensively replaces zero/negative inputs with safe minimums so the
    computation never raises (log10 / div-by-zero). A video with 0 views
    naturally scores ~0 since log10(1+1) ≈ 0.30 dominated by all-tiny terms.
    """
    v = max(int(views), 1)
    m = max(int(niche_median_views), 1)
    a = max(float(age_hours), 24.0)

    recency_factor = v / a
    engagement_rate = (max(int(likes), 0) + 4 * max(int(comments), 0)) / v
    niche_normalized = v / m

    return (
        math.log10(recency_factor + 1)
        * (0.5 + min(engagement_rate * 50, 1.5))
        * math.log10(niche_normalized + 1)
    )


def compute_niche_median(view_counts: Iterable[int]) -> int:
    """Median view count; returns 1 on empty input (cold-start safe denominator)."""
    values = [int(v) for v in view_counts if v is not None]
    if not values:
        return 1
    return int(statistics.median(values))
