"""mostReplayed heatmap fetcher (Phase 3).

Hits YouTube's undocumented Innertube endpoint at /youtubei/v1/next (the watch-
page renderer). The /player endpoint, despite its name, returns a stripped-down
payload without the heatmap. /next is the same endpoint the YouTube web client
uses to populate the timeline UI.

NOT a YouTube Data API v3 call and NOT routed through QuotaLedger.

Fail-open contract: any error (4xx, 5xx, network, missing JSON path) returns
None. The caller counts None as a miss in the run-level heatmap_hit_rate;
we do not raise.

Schema (live as of 2026-04, may drift):
  frameworkUpdates.entityBatchUpdate.mutations[].payload
    .macroMarkersListEntity.markersList.markers[]
    {startMillis (str), durationMillis (str), intensityScoreNormalized (float)}
"""

from __future__ import annotations

from typing import Any, Optional

import requests
from loguru import logger

from src.selector.windows import HeatMarker

INNERTUBE_URL = "https://www.youtube.com/youtubei/v1/next"
INNERTUBE_CONTEXT = {
    "client": {
        "clientName": "WEB",
        "clientVersion": "2.20241201.00.00",
        "hl": "en",
        "gl": "US",
    }
}
TIMEOUT_SECONDS = 5.0


def _post_once(video_id: str, timeout: float = TIMEOUT_SECONDS) -> Optional[dict[str, Any]]:
    body = {
        "context": INNERTUBE_CONTEXT,
        "videoId": video_id,
        "playbackContext": {
            "contentPlaybackContext": {"currentUrl": f"/watch?v={video_id}"}
        },
    }
    try:
        resp = requests.post(INNERTUBE_URL, json=body, timeout=timeout)
    except requests.RequestException as exc:
        logger.info(f"heatmap fetch network error for {video_id}: {exc}")
        return None
    if resp.status_code >= 500:
        logger.info(f"heatmap fetch 5xx for {video_id}: status={resp.status_code}")
        return None
    if resp.status_code >= 400:
        logger.info(f"heatmap fetch 4xx for {video_id}: status={resp.status_code}")
        return None
    try:
        return resp.json()
    except ValueError as exc:
        logger.info(f"heatmap response not JSON for {video_id}: {exc}")
        return None


def fetch_player_payload(video_id: str) -> Optional[dict[str, Any]]:
    """One retry on connection error / 5xx; fail-open returns None."""
    payload = _post_once(video_id)
    if payload is None:
        payload = _post_once(video_id)
    return payload


def parse_heat_markers(payload: dict[str, Any]) -> list[HeatMarker]:
    """Walk frameworkUpdates...macroMarkersListEntity.markersList.markers[].

    Returns [] when any path is missing (video has no heatmap data).
    """
    try:
        mutations = payload["frameworkUpdates"]["entityBatchUpdate"]["mutations"]
    except (KeyError, TypeError):
        return []

    if not isinstance(mutations, list):
        return []

    out: list[HeatMarker] = []
    for mut in mutations:
        try:
            entity = mut["payload"]["macroMarkersListEntity"]
            markers = entity["markersList"]["markers"]
        except (KeyError, TypeError):
            continue
        if not isinstance(markers, list):
            continue
        for m in markers:
            try:
                start_ms = float(m["startMillis"])
                duration_ms = float(m["durationMillis"])
                intensity = float(m["intensityScoreNormalized"])
            except (KeyError, TypeError, ValueError):
                continue
            out.append(HeatMarker(
                start_s=start_ms / 1000.0,
                duration_s=duration_ms / 1000.0,
                intensity=intensity,
            ))
    return out


def fetch_heatmap(video_id: str) -> Optional[list[HeatMarker]]:
    """Fetch + parse. Returns None on network/parse failure (no markers found
    is distinct from network failure: returns []).

    The caller treats:
      - None  → miss for hit-rate purposes
      - []    → also miss (video has no heatmap)
      - [...] → hit
    """
    payload = fetch_player_payload(video_id)
    if payload is None:
        return None
    return parse_heat_markers(payload)
