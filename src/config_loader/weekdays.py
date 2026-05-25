"""Weekday token parsing for upload_weekdays config."""

from __future__ import annotations

from typing import Iterable

# Python datetime.weekday(): Monday=0 … Sunday=6
_NAME_TO_INDEX: dict[str, int] = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}


def parse_upload_weekdays(tokens: Iterable[str | int] | None) -> frozenset[int]:
    """Normalize weekday tokens to a set of integer indices (Monday=0).

    Empty or ``None`` ⇒ all seven weekdays (backward compatible).
    """
    if tokens is None:
        return frozenset(range(7))
    token_list = list(tokens)
    if not token_list:
        return frozenset(range(7))

    indices: set[int] = set()
    for token in token_list:
        if isinstance(token, int):
            if not 0 <= token <= 6:
                raise ValueError(f"weekday integer out of range 0..6: {token!r}")
            indices.add(token)
            continue

        key = str(token).strip().lower()
        if key.isdigit():
            value = int(key)
            if not 0 <= value <= 6:
                raise ValueError(f"weekday integer out of range 0..6: {value!r}")
            indices.add(value)
            continue

        if key not in _NAME_TO_INDEX:
            raise ValueError(f"unrecognized weekday token: {token!r}")
        indices.add(_NAME_TO_INDEX[key])

    return frozenset(indices)
