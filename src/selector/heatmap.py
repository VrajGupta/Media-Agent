"""mostReplayed heatmap fetcher (Phase 3).

Hits YouTube's undocumented Innertube endpoint at /youtubei/v1/player. This is
NOT a YouTube Data API v3 call and is NOT routed through QuotaLedger.

Fail-open contract: any error (4xx, 5xx, network, missing JSON path) returns
None. The caller counts None as a miss in the run-level heatmap_hit_rate;
we do not raise.
"""

from __future__ import annotations

from typing import Any, Optional

import requests
from loguru import logger

from src.selector.windows import HeatMarker

INNERTUBE_URL = "https://www.youtube.com/youtubei/v1/player"
INNERTUBE_CONTEXT = {
    "client": {
        "clientName": "WEB",
        "clientVersion": "2.20240101.00.00",
    }
}
TIMEOUT_SECONDS = 5.0


def _post_once(video_id: str, timeout: float = TIMEOUT_SECONDS) -> Optional[dict[str, Any]]:
    body = {"context": INNERTUBE_CONTEXT, "videoId": video_id}
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
    """Walk playerOverlays...heatMarkers[]. Returns [] if any path is missing."""
    try:
        markers_map = (
            payload["playerOverlays"]["playerOverlayRenderer"]
                   ["decoratedPlayerBarRenderer"]["decoratedPlayerBarRenderer"]
                   ["playerBar"]["multiMarkersPlayerBarRenderer"]["markersMap"]
        )
    except (KeyError, TypeError):
        return []

    out: list[HeatMarker] = []
    for entry in markers_map:
        try:
            heat_markers = entry["value"]["heatmap"]["heatmapRenderer"]["heatMarkers"]
        except (KeyError, TypeError):
            continue
        for m in heat_markers:
            try:
                renderer = m["heatMarkerRenderer"]
                start_ms = float(renderer["timeRangeStartMillis"])
                duration_ms = float(renderer["markerDurationMillis"])
                intensity = float(renderer["heatMarkerIntensityScoreNormalized"])
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
