"""Pure slot allocator. No DB, no I/O, no clock — caller injects now_local.

Given a list of clip_ids and a slot grid (days × times-of-day in cfg.timezone),
emit (clip_id, local_dt, utc_dt) assignments in chronological slot order.

Slots earlier than `now_local + lead_minutes` are filtered out so we never ask
YouTube to publish in the past on a fresh weekly_run. Overflow clip_ids
(beyond the slot grid capacity) are returned separately and remain unscheduled.

Timezone math uses `zoneinfo` so DST transitions are handled correctly even
though the canonical runtime path (Asia/Singapore) has no DST. The cross-TZ
purity tests in tests/test_slot_planner_allocator.py exercise spring-forward
and fall-back to keep the code from regressing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import List, Tuple
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class SlotAssignment:
    clip_id: str
    slot_local_dt: datetime          # tz-aware in the supplied timezone_name
    slot_utc_dt: datetime            # tz-aware UTC
    slot_local_str: str              # "YYYY-MM-DD HH:MM" in cfg.timezone

    @property
    def filename_date(self) -> str:
        """Date portion for the slot-named filename: 'YYYY-MM-DD'."""
        return self.slot_local_dt.strftime("%Y-%m-%d")

    @property
    def filename_hhmm(self) -> str:
        """Time portion for the slot-named filename: 'HHMM'."""
        return self.slot_local_dt.strftime("%H%M")


def _parse_hhmm(s: str) -> time:
    """Parse 'HH:MM' → datetime.time. Raises ValueError on malformed input."""
    parts = s.split(":")
    if len(parts) != 2:
        raise ValueError(f"slot time must be HH:MM, got {s!r}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"slot time out of range: {s!r}")
    return time(hour=h, minute=m)


def allocate_slots(
    *,
    clip_ids: List[str],
    now_local: datetime,
    upload_slots: List[str],
    days_per_run: int,
    clips_per_day: int,
    timezone_name: str,
    min_lead_minutes: int = 20,
) -> Tuple[List[SlotAssignment], List[str]]:
    """Assign each clip to a slot in chronological order.

    Returns (assignments, overflow_clip_ids).
      - assignments: one SlotAssignment per clip in input order, up to the
        slot-grid capacity.
      - overflow_clip_ids: clip_ids that did not fit (count > capacity).

    Capacity = min(len(eligible_slots_after_lead_filter),
                   clips_per_day * days_per_run).

    The cap is `clips_per_day * days_per_run` (not
    `len(upload_slots) * days_per_run`) so a config with more slot times of
    day than `clips_per_day` only fills the first `clips_per_day` slots per
    day — preserving the user's stated weekly cadence.
    """
    if now_local.tzinfo is None:
        raise ValueError("now_local must be timezone-aware")
    if not upload_slots:
        return ([], list(clip_ids))
    if days_per_run <= 0 or clips_per_day <= 0:
        return ([], list(clip_ids))

    tz = ZoneInfo(timezone_name)
    if now_local.tzinfo != tz and now_local.utcoffset() != now_local.astimezone(tz).utcoffset():
        # Coerce now_local into the requested zone for date arithmetic.
        now_local = now_local.astimezone(tz)

    threshold = now_local + timedelta(minutes=int(min_lead_minutes))
    parsed_slots = [_parse_hhmm(s) for s in upload_slots]
    # Cap how many slot-times-of-day we use per day to clips_per_day.
    daily_slots = parsed_slots[:clips_per_day]

    grid: List[datetime] = []
    base_date = now_local.date()
    for day_offset in range(days_per_run):
        day = base_date + timedelta(days=day_offset)
        for slot_time in daily_slots:
            local_dt = datetime(
                day.year, day.month, day.day,
                slot_time.hour, slot_time.minute,
                tzinfo=tz,
            )
            grid.append(local_dt)

    # Filter past slots (those before threshold).
    eligible = [dt for dt in grid if dt >= threshold]
    # Sort defensively (already chronological by construction, but be explicit).
    eligible.sort()

    capacity = min(len(eligible), clips_per_day * days_per_run)
    eligible = eligible[:capacity]

    assignments: List[SlotAssignment] = []
    for i, clip_id in enumerate(clip_ids[:capacity]):
        local_dt = eligible[i]
        utc_dt = local_dt.astimezone(timezone.utc)
        slot_local_str = local_dt.strftime("%Y-%m-%d %H:%M")
        assignments.append(SlotAssignment(
            clip_id=clip_id,
            slot_local_dt=local_dt,
            slot_utc_dt=utc_dt,
            slot_local_str=slot_local_str,
        ))

    overflow = list(clip_ids[capacity:])
    return (assignments, overflow)
