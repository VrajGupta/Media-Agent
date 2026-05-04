"""Phase 5 — pad_publish_at + format_publish_at_iso_z behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.uploader.publish_at import format_publish_at_iso_z, pad_publish_at


def _utc(year=2026, month=5, day=4, hour=12, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def test_pad_needed_close_to_now():
    """publish_at 5 min from now < threshold (now + 20 min) → padded."""
    now = _utc()
    publish = now + timedelta(minutes=5)
    padded, was_padded = pad_publish_at(publish, now, lead_minutes=20)
    assert was_padded is True
    assert padded == now + timedelta(minutes=20)


def test_pad_not_needed_far_future():
    """publish_at 1 hour from now > threshold → unchanged."""
    now = _utc()
    publish = now + timedelta(hours=1)
    padded, was_padded = pad_publish_at(publish, now, lead_minutes=20)
    assert was_padded is False
    assert padded == publish


def test_pad_boundary_exactly_at_threshold_unchanged():
    """publish_at == now + 20 min: function uses strict <, so this is unchanged.
    Regression: an earlier draft of the plan said 'returns padded' here; the
    actual implementation is correct (boundary returns original).
    """
    now = _utc()
    publish = now + timedelta(minutes=20)  # exactly at threshold
    padded, was_padded = pad_publish_at(publish, now, lead_minutes=20)
    assert was_padded is False
    assert padded == publish


def test_pad_naive_publish_at_raises():
    now = _utc()
    naive = datetime(2026, 5, 4, 13, 0, 0)  # no tzinfo
    with pytest.raises(ValueError, match="naive"):
        pad_publish_at(naive, now)


def test_pad_idempotent_repeat_call_returns_same():
    """A second call with the already-padded value as input returns the same
    padded value with was_padded=False (it's now exactly at threshold; strict <
    means unchanged)."""
    now = _utc()
    publish = now + timedelta(minutes=5)
    padded1, _ = pad_publish_at(publish, now, lead_minutes=20)
    padded2, was_padded2 = pad_publish_at(padded1, now, lead_minutes=20)
    assert padded1 == padded2
    assert was_padded2 is False  # boundary case


def test_format_iso_z_emits_z_suffix_never_plus_zero():
    dt = _utc(2026, 5, 4, 13, 0, 0)
    s = format_publish_at_iso_z(dt)
    assert s == "2026-05-04T13:00:00Z"
    assert "+00:00" not in s


def test_format_iso_z_naive_raises():
    with pytest.raises(ValueError, match="naive"):
        format_publish_at_iso_z(datetime(2026, 5, 4, 13, 0, 0))
