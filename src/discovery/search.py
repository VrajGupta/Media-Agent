"""YouTube search.list wrapper, ledger-metered.

Conservative quota recording (matches Google's billing):
- Preflight `check_or_raise` raises before the call → records nothing.
- HTTP response from Google (any status, including 4xx/5xx) → records.
- Network failure before reaching Google (socket.timeout, ConnectionError) → no record.

Tenacity retry/backoff is intentionally NOT added here — it's a Phase 7 task.
"""

from __future__ import annotations

import socket
from datetime import datetime, timedelta, timezone

from googleapiclient.errors import HttpError

from src.quota_ledger import QuotaLedger

ENDPOINT = "search.list"


def _call_with_ledger(api_request, ledger: QuotaLedger, units: int, endpoint: str):
    ledger.check_or_raise(units, endpoint)
    try:
        response = api_request.execute()
    except HttpError:
        ledger.record(endpoint, units)
        raise
    except (socket.timeout, ConnectionError):
        # request never reached Google's edge — do not record
        raise
    ledger.record(endpoint, units)
    return response


def search_video_ids(
    youtube,
    ledger: QuotaLedger,
    keyword: str,
    *,
    max_inspected: int,
    recency_window_days: int,
    page_size: int,
    search_unit_cost: int,
) -> list[str]:
    """Paginate search.list until `max_inspected` IDs collected or pages exhausted."""
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=recency_window_days)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    # YouTube can legitimately return the same videoId on adjacent pages as the
    # ranking shifts. Dedup against a seen-set so we count unique IDs against
    # max_inspected and never score the same video twice.
    ids: list[str] = []
    seen: set[str] = set()
    page_token: str | None = None
    while len(ids) < max_inspected:
        request = youtube.search().list(
            q=keyword,
            type="video",
            part="id",
            relevanceLanguage="en",
            order="relevance",
            publishedAfter=published_after,
            videoDuration="any",
            maxResults=min(50, page_size),
            pageToken=page_token,
        )
        response = _call_with_ledger(request, ledger, search_unit_cost, ENDPOINT)
        for item in response.get("items", []):
            vid_id = item.get("id", {}).get("videoId")
            if vid_id and vid_id not in seen:
                seen.add(vid_id)
                ids.append(vid_id)
                if len(ids) >= max_inspected:
                    break
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return ids
