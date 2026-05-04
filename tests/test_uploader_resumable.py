"""Phase 5 — do_resumable_upload behavior + ledger conservatism."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from src.quota_ledger import QuotaExceeded, QuotaLedger
from src.state import Repository, connect, initialize_schema
from src.uploader.resumable import do_resumable_upload
from tests.conftest import make_http_error


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


def test_connection_error_does_not_record(tmp_path):
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
    # Never reached YouTube → no record.
    assert ledger.today_total() == 0


def test_socket_timeout_does_not_record(tmp_path):
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


def test_success_returns_video_id_and_records_ledger(tmp_path):
    ledger = _ledger(tmp_path)
    youtube = _youtube_with_response("ABCD1234")

    with patch("src.uploader.resumable.MediaFileUpload"):
        video_id = do_resumable_upload(
            youtube, ledger, body={}, file_path="/tmp/x.mp4", units=1600,
        )
    assert video_id == "ABCD1234"
    assert ledger.today_total() == 1600
