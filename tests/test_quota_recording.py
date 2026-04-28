"""Conservative quota recording: HTTP response from Google -> record;
network failure before reaching Google -> no record."""

import pytest

from src.discovery.search import _call_with_ledger
from src.quota_ledger import QuotaLedger
from src.state import connect, initialize_schema
from tests.conftest import FakeRequest, make_http_error


def _fresh_ledger(tmp_path):
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return conn, QuotaLedger(conn, ceiling_units=10_000)


def _quota_count(conn) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM quota_usage").fetchone()
    return int(row["c"])


def test_records_on_http_500_error(tmp_path):
    """Google processed the request and may have billed -> record."""
    conn, ledger = _fresh_ledger(tmp_path)
    req = FakeRequest(raises=make_http_error(500))

    with pytest.raises(Exception):
        _call_with_ledger(req, ledger, units=100, endpoint="search.list")

    assert _quota_count(conn) == 1
    assert ledger.today_total() == 100


def test_records_on_http_403_quota_error(tmp_path):
    """quotaExceeded is a 403 — Google saw it, count it."""
    conn, ledger = _fresh_ledger(tmp_path)
    req = FakeRequest(raises=make_http_error(403, reason="quotaExceeded"))

    with pytest.raises(Exception):
        _call_with_ledger(req, ledger, units=100, endpoint="search.list")

    assert _quota_count(conn) == 1


def test_skips_on_connection_error(tmp_path):
    """Connection failed before reaching Google -> nothing was billed."""
    conn, ledger = _fresh_ledger(tmp_path)
    req = FakeRequest(raises=ConnectionError("dns lookup failed"))

    with pytest.raises(ConnectionError):
        _call_with_ledger(req, ledger, units=100, endpoint="search.list")

    assert _quota_count(conn) == 0
    assert ledger.today_total() == 0


def test_records_on_success(tmp_path):
    conn, ledger = _fresh_ledger(tmp_path)
    req = FakeRequest(response={"items": []})

    out = _call_with_ledger(req, ledger, units=100, endpoint="search.list")

    assert out == {"items": []}
    assert _quota_count(conn) == 1
    assert ledger.today_total() == 100


def test_preflight_does_not_record_when_ceiling_hit(tmp_path):
    """If the next call would exceed the ceiling, raise BEFORE making the call."""
    conn, ledger = _fresh_ledger(tmp_path)
    # Manually fill the ledger to just below ceiling
    ledger.record("search.list", 9_950)
    pre_count = _quota_count(conn)

    req = FakeRequest(response={"items": []})  # would never get called
    from src.quota_ledger import QuotaExceeded
    with pytest.raises(QuotaExceeded):
        _call_with_ledger(req, ledger, units=100, endpoint="search.list")

    # Only the manual record above; no extra row from the failed preflight.
    assert _quota_count(conn) == pre_count
