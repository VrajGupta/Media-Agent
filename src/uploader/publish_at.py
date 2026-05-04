"""Future-too-near padding for YouTube publishAt timestamps.

YouTube rejects videos.insert calls whose status.publishAt is in the past or
too close to "now". Empirically the floor is ~15 minutes; we use 20 as a
safety margin to absorb upload time on slow connections.

Pure module: no DB, no I/O, no time mocking. The caller passes the current
time explicitly so tests are deterministic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Tuple


def pad_publish_at(
    publish_at_utc: datetime,
    now: datetime,
    lead_minutes: int = 20,
) -> Tuple[datetime, bool]:
    """Pad a near-future publishAt to at least now + lead_minutes.

    Returns (padded_publish_at, was_padded).

    - If publish_at_utc < now + lead_minutes (strictly less): returns the
      padded threshold and was_padded=True.
    - Otherwise: returns publish_at_utc unchanged and was_padded=False.

    Raises ValueError if either datetime is naive (missing tzinfo) — defensive
    guard against silently mixing UTC + local times.
    """
    if publish_at_utc.tzinfo is None or publish_at_utc.tzinfo.utcoffset(publish_at_utc) is None:
        raise ValueError(
            f"publish_at_utc must be timezone-aware; got naive {publish_at_utc!r}"
        )
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError(f"now must be timezone-aware; got naive {now!r}")

    threshold = now + timedelta(minutes=int(lead_minutes))
    if publish_at_utc < threshold:
        return (threshold, True)
    return (publish_at_utc, False)


def format_publish_at_iso_z(dt: datetime) -> str:
    """Format a UTC datetime as the YouTube-canonical ISO 8601 'Z' string.

    Example: '2026-05-04T12:34:56Z'. Always uses UTC + 'Z' suffix; never
    emits '+00:00' so dry-run JSON is byte-stable across systems.

    Raises ValueError on naive datetimes.
    """
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"dt must be timezone-aware; got naive {dt!r}")
    utc = dt.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
