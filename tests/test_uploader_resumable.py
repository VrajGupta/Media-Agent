"""Phase 5 — do_resumable_upload behavior + ledger conservatism.

Phase 7 update: tenacity retry on transient transport errors. The Phase 5
ledger-recording invariants are unchanged — tests now also verify that
retries don't double-record and that HttpError fails fast (no retry).
"""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest
import tenacity

from src.quota_ledger import QuotaExceeded, QuotaLedger
from src.state import Repository, connect, initialize_schema
from src.uploader.resumable import do_resumable_upload
from src.uploader import resumable as resumable_mod
from tests.conftest import make_http_error


@pytest.fixture(autouse=True)
def _no_sleep_in_retry(monkeypatch):
    """Override the tenacity wait so retry tests don't actually sleep 2s.
    Applies to every test in this module — there's no real-clock test here."""
    monkeypatch.setattr(
        resumable_mod._drive_request_to_completion.retry,
        "wait",
        tenacity.wait_none(),
    )


def _ledger(tmp_path, *, ceiling=9000):
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return QuotaLedger(conn, ceiling_units=ceiling)


def _youtube_with_response(response_id="FAKE_ID"):
    """Construct a MagicMock youtube client whose insert(...).next_chunk()
    returns (None, {"id": response_id}) on first call (single-chunk happy path).
    """
    youtube = MagicMock()
    request = MagicMock()
    request.next_chunk.return_value = (None, {"id": response_id})
    youtube.videos.return_value.insert.return_value = request
    return youtube


def test_quota_preflight_raises_before_media_constructed(tmp_path):
    ledger = _ledger(tmp_path, ceiling=100)
    # Pre-fill quota so 1600-unit insert would push over.
    ledger.record("videos.insert", 600)
    youtube = _youtube_with_response()

    with patch("src.uploader.resumable.MediaFileUpload") as mfu:
        with pytest.raises(QuotaExceeded):
            do_resumable_upload(
                youtube, ledger, body={}, file_path="/tmp/anything.mp4", units=1600,
            )
        assert mfu.call_count == 0  # never reached
    # ledger NOT recorded on pre-flight refusal.
    assert ledger.today_total() == 600


def test_http_error_records_ledger_then_reraises(tmp_path):
    ledger = _ledger(tmp_path)
    youtube = MagicMock()
    request = MagicMock()
    err = make_http_error(400, "Bad Request")
    request.next_chunk.side_effect = err
    youtube.videos.return_value.insert.return_value = request

    with patch("src.uploader.resumable.MediaFileUpload"):
        with pytest.raises(type(err)):
            do_resumable_upload(
                youtube, ledger, body={}, file_path="/tmp/x.mp4", units=1600,
            )
    # YouTube responded → ledger recorded the cost.
    assert ledger.today_total() == 1600


def test_connection_error_after_3_retries_does_not_record(tmp_path):
    """Phase 7: tenacity retries ConnectionError up to 3 attempts.
    All three fail → reraise ConnectionError → ledger NOT recorded."""
    ledger = _ledger(tmp_path)
    youtube = MagicMock()
    request = MagicMock()
    request.next_chunk.side_effect = ConnectionError("DNS failure")
    youtube.videos.return_value.insert.return_value = request

    with patch("src.uploader.resumable.MediaFileUpload"):
        with pytest.raises(ConnectionError):
            do_resumable_upload(
                youtube, ledger, body={}, file_path="/tmp/x.mp4", units=1600,
            )
    # Never reached YouTube's edge → no record.
    assert ledger.today_total() == 0
    # Phase 7: retry attempted 3 times.
    assert request.next_chunk.call_count == 3


def test_socket_timeout_after_3_retries_does_not_record(tmp_path):
    ledger = _ledger(tmp_path)
    youtube = MagicMock()
    request = MagicMock()
    request.next_chunk.side_effect = socket.timeout("read timeout")
    youtube.videos.return_value.insert.return_value = request

    with patch("src.uploader.resumable.MediaFileUpload"):
        with pytest.raises(socket.timeout):
            do_resumable_upload(
                youtube, ledger, body={}, file_path="/tmp/x.mp4", units=1600,
            )
    assert ledger.today_total() == 0
    assert request.next_chunk.call_count == 3


def test_success_returns_video_id_and_records_ledger(tmp_path):
    ledger = _ledger(tmp_path)
    youtube = _youtube_with_response("ABCD1234")

    with patch("src.uploader.resumable.MediaFileUpload"):
        video_id = do_resumable_upload(
            youtube, ledger, body={}, file_path="/tmp/x.mp4", units=1600,
        )
    assert video_id == "ABCD1234"
    assert ledger.today_total() == 1600


# ---- Phase 7 retry semantics ------------------------------------------------


def test_retry_recovers_after_transient_connection_error(tmp_path):
    """Phase 7: ConnectionError → ConnectionError → success.
    Ledger records exactly once (the success); does NOT double-record."""
    ledger = _ledger(tmp_path)
    youtube = MagicMock()
    request = MagicMock()
    request.next_chunk.side_effect = [
        ConnectionError("blip 1"),
        ConnectionError("blip 2"),
        (None, {"id": "RECOVERED_ID"}),
    ]
    youtube.videos.return_value.insert.return_value = request

    with patch("src.uploader.resumable.MediaFileUpload"):
        video_id = do_resumable_upload(
            youtube, ledger, body={}, file_path="/tmp/x.mp4", units=1600,
        )
    assert video_id == "RECOVERED_ID"
    # Recorded exactly ONCE (the successful attempt).
    assert ledger.today_total() == 1600
    assert request.next_chunk.call_count == 3


def test_http_error_fails_fast_no_retry(tmp_path):
    """Phase 7: HttpError is NOT in the retry list. next_chunk called once.
    Ledger records the cost once and HttpError reraises immediately."""
    ledger = _ledger(tmp_path)
    youtube = MagicMock()
    request = MagicMock()
    err = make_http_error(403, "quotaExceeded")
    request.next_chunk.side_effect = err
    youtube.videos.return_value.insert.return_value = request

    with patch("src.uploader.resumable.MediaFileUpload"):
        with pytest.raises(type(err)):
            do_resumable_upload(
                youtube, ledger, body={}, file_path="/tmp/x.mp4", units=1600,
            )
    # Single attempt only — no retry on HttpError.
    assert request.next_chunk.call_count == 1
    # Ledger recorded once (request reached Google's edge).
    assert ledger.today_total() == 1600


def test_check_or_raise_not_repeated_across_retries(tmp_path):
    """Phase 7: tenacity wraps the inner driver, NOT do_resumable_upload.
    check_or_raise must run exactly once even if the inner driver retries."""
    ledger = MagicMock(wraps=_ledger(tmp_path))
    youtube = MagicMock()
    request = MagicMock()
    request.next_chunk.side_effect = [
        ConnectionError("blip"),
        (None, {"id": "OK"}),
    ]
    youtube.videos.return_value.insert.return_value = request

    with patch("src.uploader.resumable.MediaFileUpload"):
        do_resumable_upload(youtube, ledger, body={}, file_path="/tmp/x.mp4", units=1600)
    # Exactly one preflight check_or_raise.
    assert ledger.check_or_raise.call_count == 1
    # Exactly one record (after success).
    assert ledger.record.call_count == 1
