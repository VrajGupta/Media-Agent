from src.discovery.virality import parse_iso8601_duration


def test_seconds_only():
    assert parse_iso8601_duration("PT30S") == 30


def test_minutes_only():
    assert parse_iso8601_duration("PT1M") == 60


def test_minutes_and_seconds():
    assert parse_iso8601_duration("PT1M30S") == 90


def test_hours_only():
    assert parse_iso8601_duration("PT1H") == 3600


def test_full_form():
    assert parse_iso8601_duration("PT1H2M3S") == 3600 + 120 + 3


def test_with_days():
    assert parse_iso8601_duration("P1DT2H") == 86400 + 7200


def test_empty_string():
    assert parse_iso8601_duration("") == 0


def test_garbage():
    assert parse_iso8601_duration("not a duration") == 0
