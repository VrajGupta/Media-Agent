"""Shared pytest fixtures and helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import httplib2
from googleapiclient.errors import HttpError

# Make `src.*` importable when running `pytest` from the repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def make_http_error(status: int, reason: str = "Server Error") -> HttpError:
    """Construct a googleapiclient HttpError with a given status code.

    HttpError's constructor wants an httplib2 Response (dict-like with 'status')
    and bytes content. This helper hides the awkward setup.
    """
    resp = httplib2.Response({"status": status, "reason": reason})
    resp.reason = reason  # httplib2.Response stores reason as attr too
    content = ('{"error":{"code":' + str(status) + ',"message":"' + reason + '"}}').encode()
    return HttpError(resp, content)


class FakeRequest:
    """Mimics googleapiclient's request object: only `.execute()` matters."""

    def __init__(self, *, raises: Exception | None = None, response: dict | None = None):
        self._raises = raises
        self._response = response

    def execute(self):
        if self._raises is not None:
            raise self._raises
        return self._response or {}
