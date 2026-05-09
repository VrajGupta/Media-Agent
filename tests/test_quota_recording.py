"""Conservative quota recording: HTTP response from Google -> record;
network failure before reaching Google -> no record.

Phase 7: tenacity retry on transient transport errors. Wrapping is on the
inner _execute_with_retry helper, so check_or_raise still runs exactly once
and ledger.record runs at most once per logical attempt.
"""

import pytest
import tenacity

from src.discovery import search as search_mod
from src.discovery.search import _call_with_ledger
from src.quota_ledger import QuotaLedger
from src.state import connect, initialize_schema
from tests.conftest import FakeRequest, make_http_error


@pytest.fixture(autouse=True)
def _no_sleep_in_retry(monkeypatch):
    """Override the tenacity wait so retry tests don't actually sleep 2s."""
    monkeypatch.setattr(
        search_mod._execute_with_retry.retry,
        "wait",
        tenacity.wait_none(),
    )


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


class _CountingRequest:
    """Tracks execute() call count + supports a sequence of side effects."""

    def __init__(self, side_effects):
        self._effects = list(side_effects)
        self.call_count = 0

    def execute(self):
        self.call_count += 1
        item = self._effects.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_retry_recovers_after_transient_connection_error(tmp_path):
    """Phase 7: ConnectionError → ConnectionError → success. Ledger records once."""
    conn, ledger = _fresh_ledger(tmp_path)
    req = _CountingRequest([
        ConnectionError("blip 1"),
        ConnectionError("blip 2"),
        {"items": ["ok"]},
    ])
    out = _call_with_ledger(req, ledger, units=100, endpoint="search.list")
    assert out == {"items": ["ok"]}
    # Recorded exactly ONCE (the successful attempt).
    assert _quota_count(conn) == 1
    assert ledger.today_total() == 100
    assert req.call_count == 3


def test_3_connection_errors_no_record_3_attempts(tmp_path):
    """Phase 7: 3× ConnectionError → reraises, 0 ledger records, 3 attempts."""
    conn, ledger = _fresh_ledger(tmp_path)
    req = _CountingRequest([
        ConnectionError("dns 1"),
        ConnectionError("dns 2"),
        ConnectionError("dns 3"),
    ])
    with pytest.raises(ConnectionError):
        _call_with_ledger(req, ledger, units=100, endpoint="search.list")
    assert _quota_count(conn) == 0
    assert req.call_count == 3


def test_http_error_fails_fast_no_retry(tmp_path):
    """Phase 7: HttpError(429) is NOT in the retry list. Single attempt; record once."""
    conn, ledger = _fresh_ledger(tmp_path)
    req = _CountingRequest([make_http_error(429, "Too Many Requests")])
    with pytest.raises(Exception):
        _call_with_ledger(req, ledger, units=100, endpoint="search.list")
    # No retry — single attempt only.
    assert req.call_count == 1
    # Ledger recorded once (request reached Google's edge).
    assert _quota_count(conn) == 1


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
