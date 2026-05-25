"""Pure allocator tests. No DB, no I/O — only `now_local` injected."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.slot_planner.allocator import allocate_slots


SGT = ZoneInfo("Asia/Singapore")


def _sgt(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=SGT)


def test_empty_clip_list_returns_empty():
    assignments, overflow = allocate_slots(
        clip_ids=[],
        now_local=_sgt(2026, 5, 4, 2, 0),
        upload_slots=["09:00", "13:00", "17:00", "21:00"],
        days_per_run=7,
        clips_per_day=4,
        timezone_name="Asia/Singapore",
    )
    assert assignments == []
    assert overflow == []


def test_empty_upload_slots_overflows_everything():
    assignments, overflow = allocate_slots(
        clip_ids=["a", "b"],
        now_local=_sgt(2026, 5, 4, 2, 0),
        upload_slots=[],
        days_per_run=7,
        clips_per_day=4,
        timezone_name="Asia/Singapore",
    )
    assert assignments == []
    assert overflow == ["a", "b"]


def test_weekly_run_sunday_02_produces_today_09_as_first_slot():
    """Canonical case: weekly_run on Sunday 02:00 SGT -> first slot today 09:00 SGT."""
    sunday_0200 = _sgt(2026, 5, 3, 2, 0)  # Sunday
    assignments, overflow = allocate_slots(
        clip_ids=["c1"],
        now_local=sunday_0200,
        upload_slots=["09:00", "13:00", "17:00", "21:00"],
        days_per_run=7,
        clips_per_day=4,
        timezone_name="Asia/Singapore",
    )
    assert len(assignments) == 1
    assert overflow == []
    a = assignments[0]
    assert a.clip_id == "c1"
    assert a.slot_local_dt.year == 2026
    assert a.slot_local_dt.month == 5
    assert a.slot_local_dt.day == 3
    assert a.slot_local_dt.hour == 9
    assert a.slot_local_dt.minute == 0
    assert a.slot_local_str == "2026-05-03 09:00"
    # UTC = SGT - 8h
    assert a.slot_utc_dt.tzinfo is timezone.utc
    assert a.slot_utc_dt.hour == 1


def test_exactly_n_clips_fills_all_slots():
    sunday_0200 = _sgt(2026, 5, 3, 2, 0)
    n = 4 * 7
    clip_ids = [f"c{i}" for i in range(n)]
    assignments, overflow = allocate_slots(
        clip_ids=clip_ids,
        now_local=sunday_0200,
        upload_slots=["09:00", "13:00", "17:00", "21:00"],
        days_per_run=7,
        clips_per_day=4,
        timezone_name="Asia/Singapore",
    )
    assert len(assignments) == n
    assert overflow == []
    # Slots are chronological.
    for i in range(1, n):
        assert assignments[i].slot_local_dt > assignments[i - 1].slot_local_dt


def test_more_than_n_clips_overflows_to_overflow_list():
    sunday_0200 = _sgt(2026, 5, 3, 2, 0)
    clip_ids = [f"c{i}" for i in range(30)]   # 4*7=28 capacity
    assignments, overflow = allocate_slots(
        clip_ids=clip_ids,
        now_local=sunday_0200,
        upload_slots=["09:00", "13:00", "17:00", "21:00"],
        days_per_run=7,
        clips_per_day=4,
        timezone_name="Asia/Singapore",
    )
    assert len(assignments) == 28
    assert overflow == ["c28", "c29"]


def test_past_slots_filtered_within_lead_minutes():
    """Run at 09:30 SGT — first slot 09:00 was already in the past."""
    nine_thirty = _sgt(2026, 5, 3, 9, 30)
    assignments, _ = allocate_slots(
        clip_ids=["c0"],
        now_local=nine_thirty,
        upload_slots=["09:00", "13:00", "17:00", "21:00"],
        days_per_run=7,
        clips_per_day=4,
        timezone_name="Asia/Singapore",
    )
    assert len(assignments) == 1
    # 09:00 already past, 13:00 is the first eligible.
    assert assignments[0].slot_local_dt.hour == 13


def test_lead_minutes_window_pads_near_future():
    """Slot 5 minutes from now (within 20-min lead) is filtered out."""
    almost_nine = _sgt(2026, 5, 3, 8, 45)  # 15 min before 09:00 < 20 min lead
    assignments, _ = allocate_slots(
        clip_ids=["c0"],
        now_local=almost_nine,
        upload_slots=["09:00", "13:00"],
        days_per_run=1,
        clips_per_day=4,
        timezone_name="Asia/Singapore",
    )
    assert len(assignments) == 1
    assert assignments[0].slot_local_dt.hour == 13


def test_clips_per_day_caps_below_upload_slots_length():
    """upload_slots has 6 entries but clips_per_day=4 -> only first 4 per day used."""
    sunday_0200 = _sgt(2026, 5, 3, 2, 0)
    assignments, overflow = allocate_slots(
        clip_ids=[f"c{i}" for i in range(28)],
        now_local=sunday_0200,
        upload_slots=["09:00", "11:00", "13:00", "17:00", "19:00", "21:00"],
        days_per_run=7,
        clips_per_day=4,
        timezone_name="Asia/Singapore",
    )
    assert len(assignments) == 28
    assert overflow == []
    # Day 0 should have hours [9, 11, 13, 17] only — NOT 19 or 21.
    day0_hours = sorted(a.slot_local_dt.hour for a in assignments[:4])
    assert day0_hours == [9, 11, 13, 17]


def test_deterministic_order_across_reruns():
    sunday_0200 = _sgt(2026, 5, 3, 2, 0)
    args = dict(
        clip_ids=["c2", "c0", "c1"],
        now_local=sunday_0200,
        upload_slots=["09:00", "13:00"],
        days_per_run=7,
        clips_per_day=4,
        timezone_name="Asia/Singapore",
    )
    a1, _ = allocate_slots(**args)
    a2, _ = allocate_slots(**args)
    assert [a.clip_id for a in a1] == [a.clip_id for a in a2]
    # Input order honored: c2 gets first slot.
    assert a1[0].clip_id == "c2"


def test_naive_now_local_raises():
    with pytest.raises(ValueError):
        allocate_slots(
            clip_ids=["c0"],
            now_local=datetime(2026, 5, 3, 2, 0),  # naive
            upload_slots=["09:00"],
            days_per_run=7,
            clips_per_day=4,
            timezone_name="Asia/Singapore",
        )


def test_filename_helpers_format_correctly():
    sunday_0200 = _sgt(2026, 5, 3, 2, 0)
    assignments, _ = allocate_slots(
        clip_ids=["c0"],
        now_local=sunday_0200,
        upload_slots=["09:00"],
        days_per_run=1,
        clips_per_day=4,
        timezone_name="Asia/Singapore",
    )
    a = assignments[0]
    assert a.filename_date == "2026-05-03"
    assert a.filename_hhmm == "0900"


def test_dst_spring_forward_skips_invalid_local_time():
    """America/New_York: 2026-03-08 02:30 doesn't exist (spring-forward).

    zoneinfo's `fold` semantics resolve such times to the post-jump instance.
    The allocator should still produce a valid UTC datetime (no exception).
    """
    # Run at 2026-03-08 00:00 NYT — slot at 02:30 is the spring-forward gap.
    nyt = ZoneInfo("America/New_York")
    midnight_dst_day = datetime(2026, 3, 8, 0, 0, tzinfo=nyt)
    assignments, _ = allocate_slots(
        clip_ids=["c0"],
        now_local=midnight_dst_day,
        upload_slots=["02:30"],
        days_per_run=1,
        clips_per_day=4,
        timezone_name="America/New_York",
    )
    # We expect an assignment — zoneinfo resolves the gap (POSIX-style: jumps fwd).
    assert len(assignments) == 1
    a = assignments[0]
    # Resolved instant must convert to a valid UTC datetime.
    assert a.slot_utc_dt.tzinfo is timezone.utc


def test_dst_fall_back_uses_first_instance_via_zoneinfo():
    """Europe/Berlin: 2026-10-25 02:30 occurs twice (fall-back).

    zoneinfo defaults to fold=0 (the FIRST occurrence — the pre-fall-back one).
    """
    berlin = ZoneInfo("Europe/Berlin")
    midnight = datetime(2026, 10, 25, 0, 0, tzinfo=berlin)
    assignments, _ = allocate_slots(
        clip_ids=["c0"],
        now_local=midnight,
        upload_slots=["02:30"],
        days_per_run=1,
        clips_per_day=4,
        timezone_name="Europe/Berlin",
    )
    assert len(assignments) == 1
    # First occurrence in CEST (UTC+2): 2026-10-25 00:30Z.
    # If zoneinfo had picked the second (CET, UTC+1), it'd be 01:30Z.
    a = assignments[0]
    assert a.slot_utc_dt.hour == 0
    assert a.slot_utc_dt.minute == 30


def test_allowed_weekdays_restricts_to_tue_thu():
    """7-day window from Sunday assigns only on the next Tuesday and Thursday."""
    sunday_0200 = _sgt(2026, 5, 3, 2, 0)
    assignments, overflow = allocate_slots(
        clip_ids=["c1", "c2"],
        now_local=sunday_0200,
        upload_slots=["09:00"],
        days_per_run=7,
        clips_per_day=1,
        timezone_name="Asia/Singapore",
        allowed_weekdays=frozenset({1, 3}),
    )
    assert overflow == []
    assert len(assignments) == 2
    assert assignments[0].slot_local_dt.weekday() == 1
    assert assignments[0].slot_local_dt.day == 5
    assert assignments[1].slot_local_dt.weekday() == 3
    assert assignments[1].slot_local_dt.day == 7


def test_allowed_weekdays_none_matches_full_week_behavior():
    sunday_0200 = _sgt(2026, 5, 3, 2, 0)
    args = dict(
        clip_ids=["c1"],
        now_local=sunday_0200,
        upload_slots=["09:00"],
        days_per_run=7,
        clips_per_day=1,
        timezone_name="Asia/Singapore",
    )
    default_assignments, default_overflow = allocate_slots(**args)
    explicit_assignments, explicit_overflow = allocate_slots(
        **args,
        allowed_weekdays=frozenset(range(7)),
    )
    assert default_assignments == explicit_assignments
    assert default_overflow == explicit_overflow


def test_allowed_weekdays_with_no_eligible_days_overflows_all_clips():
    """Only Monday allowed, but the 1-day window is a Tuesday."""
    tuesday_0200 = _sgt(2026, 5, 5, 2, 0)
    assignments, overflow = allocate_slots(
        clip_ids=["c1", "c2"],
        now_local=tuesday_0200,
        upload_slots=["09:00"],
        days_per_run=1,
        clips_per_day=1,
        timezone_name="Asia/Singapore",
        allowed_weekdays=frozenset({0}),
    )
    assert assignments == []
    assert overflow == ["c1", "c2"]


def test_allowed_weekdays_respects_min_lead_on_target_weekday():
    """Tuesday 08:50 — today's 09:00 slot is inside the 20-min lead; next is Thursday."""
    tuesday_0850 = _sgt(2026, 5, 5, 8, 50)
    assignments, overflow = allocate_slots(
        clip_ids=["c1"],
        now_local=tuesday_0850,
        upload_slots=["09:00"],
        days_per_run=7,
        clips_per_day=1,
        timezone_name="Asia/Singapore",
        allowed_weekdays=frozenset({1, 3}),
    )
    assert overflow == []
    assert len(assignments) == 1
    assert assignments[0].slot_local_dt.weekday() == 3
    assert assignments[0].slot_local_dt.day == 7
