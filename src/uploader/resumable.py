"""Resumable YouTube videos.insert wrapper.

Single source of truth for the videos.insert quota call. The runner does
NOT separately call ledger.check_or_raise — it only catches QuotaExceeded
raised here.

Conservative ledger recording (matches src/discovery/search.py::_call_with_ledger):
- Preflight check_or_raise raises before any HTTP → no record.
- HttpError (any status, including 4xx/5xx) → YouTube responded → record then re-raise.
- ConnectionError / socket.timeout → never reached YouTube's edge → no record.

Phase 7 retry policy:
- ConnectionError / socket.timeout retried up to 3 attempts with exponential
  backoff (2s..30s). Tenacity wraps the inner next_chunk() driver only —
  check_or_raise stays exactly-once and ledger.record runs at most once
  per logical attempt.
- HttpError is NOT retried (fail-fast through the existing handler).

Resumable upload contract: we use MediaFileUpload(resumable=True, chunksize=-1)
which tells the client to send the body in a single chunk under the resumable
protocol. The API surface is `request.next_chunk()` looped until response is
not None — calling `.execute()` on a resumable request is undefined per the
google-api-python-client docs.
"""

from __future__ import annotations

import socket
from typing import Any, Mapping

import tenacity
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from src.quota_ledger import QuotaLedger

ENDPOINT = "videos.insert"


@tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_exponential(min=2, max=30),
    retry=tenacity.retry_if_exception_type((socket.timeout, ConnectionError)),
    reraise=True,
)
def _drive_request_to_completion(request: Any) -> dict:
    """Drive a resumable upload request via next_chunk() until done.

    Retries on transient transport errors only (socket.timeout/ConnectionError).
    HttpError is intentionally NOT retried — it surfaces immediately so the
    caller can record ledger units and re-raise.
    """
    response = None
    while response is None:
        # With chunksize=-1 the body is sent in one chunk so this loop
        # iterates exactly once on the happy path.
        _status, response = request.next_chunk()
    return response


def do_resumable_upload(
    youtube: Any,
    ledger: QuotaLedger,
    body: Mapping[str, Any],
    file_path: str,
    *,
    units: int,
) -> str:
    """Upload `file_path` to YouTube with `body` as the videos.insert resource.

    Returns the new YouTube `videoId` on success.

    Raises:
      - QuotaExceeded: pre-flight refused; no API call made; no ledger write.
      - HttpError: YouTube responded with an error; ledger is recorded
        BEFORE re-raising (the request reached YouTube, so quota was billed).
      - ConnectionError / socket.timeout (after 3 retry attempts): never
        reached YouTube's edge; no ledger record (matches Phase 1 conservative rule).
    """
    ledger.check_or_raise(units, ENDPOINT)

    media = MediaFileUpload(
        str(file_path),
        chunksize=-1,
        resumable=True,
        mimetype="video/mp4",
    )
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    try:
        response = _drive_request_to_completion(request)
    except HttpError:
        ledger.record(ENDPOINT, units)
        raise
    except (socket.timeout, ConnectionError):
        # Request never reached Google's edge after 3 attempts — do not record.
        raise

    ledger.record(ENDPOINT, units)
    return response["id"]
