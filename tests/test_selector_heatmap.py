"""Heatmap fetcher: parsing + fail-open behavior. requests.post monkeypatched."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import requests

from src.selector import heatmap as hm


def _fake_payload(markers: list[tuple[float, float, float]]) -> dict[str, Any]:
    """Build a Innertube player JSON with the given (start_s, duration_s, intensity) markers."""
    heat_markers = [
        {
            "heatMarkerRenderer": {
                "timeRangeStartMillis": int(s * 1000),
                "markerDurationMillis": int(d * 1000),
                "heatMarkerIntensityScoreNormalized": float(i),
            }
        }
        for (s, d, i) in markers
    ]
    return {
        "playerOverlays": {
            "playerOverlayRenderer": {
                "decoratedPlayerBarRenderer": {
                    "decoratedPlayerBarRenderer": {
                        "playerBar": {
                            "multiMarkersPlayerBarRenderer": {
                                "markersMap": [
                                    {"value": {"heatmap": {"heatmapRenderer": {"heatMarkers": heat_markers}}}}
                                ]
                            }
                        }
                    }
                }
            }
        }
    }


def _fake_response(*, status: int = 200, json_body: Any | None = None, raises: Exception | None = None):
    """A SimpleNamespace mimicking requests.Response."""
    def _json():
        if isinstance(json_body, Exception):
            raise json_body
        return json_body

    return SimpleNamespace(status_code=status, json=_json, raises=raises)


def _patch_post(monkeypatch, responses: list):
    """Sequential responses for each requests.post call. Each entry is either
    a fake response or an Exception to raise."""
    calls = {"n": 0}

    def fake_post(url, json=None, timeout=None):
        idx = calls["n"]
        calls["n"] += 1
        item = responses[idx]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(hm.requests, "post", fake_post)
    return calls


# ---- parse_heat_markers -----------------------------------------------------


def test_parse_extracts_markers():
    payload = _fake_payload([(10.0, 5.0, 0.9), (60.0, 5.0, 0.5)])
    markers = hm.parse_heat_markers(payload)
    assert len(markers) == 2
    assert markers[0].start_s == 10.0
    assert markers[0].duration_s == 5.0
    assert markers[0].intensity == 0.9
    assert markers[1].start_s == 60.0


def test_parse_returns_empty_when_path_missing():
    assert hm.parse_heat_markers({}) == []
    assert hm.parse_heat_markers({"playerOverlays": {}}) == []


def test_parse_skips_malformed_markers():
    payload = _fake_payload([(10.0, 5.0, 0.9)])
    payload["playerOverlays"]["playerOverlayRenderer"]["decoratedPlayerBarRenderer"]["decoratedPlayerBarRenderer"]["playerBar"]["multiMarkersPlayerBarRenderer"]["markersMap"][0]["value"]["heatmap"]["heatmapRenderer"]["heatMarkers"].append(
        {"heatMarkerRenderer": {"missing": "fields"}}
    )
    markers = hm.parse_heat_markers(payload)
    assert len(markers) == 1


# ---- fetch_heatmap: success + fail-open ------------------------------------


def test_fetch_success(monkeypatch):
    payload = _fake_payload([(10.0, 5.0, 0.9)])
    _patch_post(monkeypatch, [_fake_response(json_body=payload)])
    result = hm.fetch_heatmap("v1")
    assert result is not None
    assert len(result) == 1


def test_fetch_404_fails_open(monkeypatch):
    """4xx counts as a miss (None), no exception."""
    calls = _patch_post(monkeypatch, [
        _fake_response(status=404),
        _fake_response(status=404),  # retry
    ])
    assert hm.fetch_heatmap("v1") is None
    assert calls["n"] == 2  # one initial + one retry


def test_fetch_5xx_retries_then_fails_open(monkeypatch):
    payload = _fake_payload([(10.0, 5.0, 0.9)])
    calls = _patch_post(monkeypatch, [
        _fake_response(status=500),
        _fake_response(json_body=payload),  # retry succeeds
    ])
    result = hm.fetch_heatmap("v1")
    assert result is not None
    assert len(result) == 1
    assert calls["n"] == 2


def test_fetch_network_error_retries_then_fails_open(monkeypatch):
    calls = _patch_post(monkeypatch, [
        requests.ConnectionError("dns fail"),
        requests.ConnectionError("dns fail"),
    ])
    assert hm.fetch_heatmap("v1") is None
    assert calls["n"] == 2


def test_fetch_returns_empty_list_for_video_without_heatmap(monkeypatch):
    """A 200 response with no markers in the payload: returns [], not None."""
    _patch_post(monkeypatch, [_fake_response(json_body={"playerOverlays": {}})])
    result = hm.fetch_heatmap("v1")
    assert result == []
