"""Ranker: candidate_id validation, retry, fail-on-persistent-bad-output."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import requests

from src.selector import ranker as rk
from src.selector.windows import Window


def _windows(n: int = 3) -> list[Window]:
    out: list[Window] = []
    for i in range(n):
        out.append(Window(
            candidate_id=f"c{i}",
            start_s=i * 30.0,
            end_s=i * 30.0 + 30.0,
            text=f"window {i} content",
            words=[],
            heatmap_peak=(i == 0),
            source="baseline",
        ))
    return out


def _resp(content_obj: dict, status: int = 200):
    """Mimic requests.Response.raise_for_status() + .json()."""
    body = {"message": {"content": json.dumps(content_obj)}}

    def _raise():
        if status >= 400:
            raise requests.HTTPError(f"status={status}")

    return SimpleNamespace(status_code=status, raise_for_status=_raise, json=lambda: body)


def _patch_post(monkeypatch, responses: list):
    calls = {"n": 0, "prompts": []}

    def fake_post(url, json=None, timeout=None):
        idx = calls["n"]
        calls["n"] += 1
        calls["prompts"].append(json["messages"][-1]["content"] if json else "")
        item = responses[idx]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(rk.requests, "post", fake_post)
    return calls


# ---- success path -----------------------------------------------------------


def test_rank_returns_top_n(monkeypatch):
    payload = {"clips": [
        {"candidate_id": "c0", "hook": "wow", "suggested_title": "Wow Title", "score": 9.0},
        {"candidate_id": "c2", "hook": "huh", "suggested_title": "Huh Title", "score": 7.5},
    ]}
    _patch_post(monkeypatch, [_resp(payload)])
    out = rk.rank_windows(_windows(3), model="qwen2.5:3b-instruct", top_n=2)
    assert [c.candidate_id for c in out] == ["c0", "c2"]
    assert out[0].hook == "wow"
    assert out[0].suggested_title == "Wow Title"
    assert out[0].score == 9.0


# ---- candidate_id validation ------------------------------------------------


def test_unknown_candidate_id_retries_then_fails(monkeypatch):
    bad_payload = {"clips": [
        {"candidate_id": "c99", "hook": "h", "suggested_title": "T", "score": 9.0},
        {"candidate_id": "c0", "hook": "h", "suggested_title": "T", "score": 8.0},
    ]}
    calls = _patch_post(monkeypatch, [_resp(bad_payload), _resp(bad_payload)])
    with pytest.raises(rk.RankerError, match="invalid output after retry"):
        rk.rank_windows(_windows(3), model="m", top_n=2)
    assert calls["n"] == 2
    # The retry user prompt mentions "previous response was invalid".
    assert "previous response was invalid" in calls["prompts"][1]


def test_duplicate_candidate_id_retries_then_fails(monkeypatch):
    bad_payload = {"clips": [
        {"candidate_id": "c0", "hook": "h", "suggested_title": "T", "score": 9.0},
        {"candidate_id": "c0", "hook": "h", "suggested_title": "T", "score": 8.0},
    ]}
    calls = _patch_post(monkeypatch, [_resp(bad_payload), _resp(bad_payload)])
    with pytest.raises(rk.RankerError):
        rk.rank_windows(_windows(3), model="m", top_n=2)
    assert calls["n"] == 2


def test_retry_succeeds_after_first_invalid_response(monkeypatch):
    bad = {"clips": [{"candidate_id": "c99", "hook": "h", "suggested_title": "T", "score": 9.0}]}
    good = {"clips": [
        {"candidate_id": "c0", "hook": "h", "suggested_title": "T", "score": 9.0},
        {"candidate_id": "c1", "hook": "h", "suggested_title": "T", "score": 8.0},
    ]}
    _patch_post(monkeypatch, [_resp(bad), _resp(good)])
    out = rk.rank_windows(_windows(3), model="m", top_n=2)
    assert [c.candidate_id for c in out] == ["c0", "c1"]


# ---- malformed JSON ---------------------------------------------------------


def test_malformed_json_retries_then_fails(monkeypatch):
    """Content that isn't valid JSON triggers the same retry path."""
    raw_response = SimpleNamespace(
        status_code=200,
        raise_for_status=lambda: None,
        json=lambda: {"message": {"content": "{not json"}},
    )
    _patch_post(monkeypatch, [raw_response, raw_response])
    with pytest.raises(rk.RankerError):
        rk.rank_windows(_windows(3), model="m", top_n=2)


# ---- network failures -------------------------------------------------------


def test_unreachable_after_retry_raises_ranker_error(monkeypatch):
    _patch_post(monkeypatch, [
        requests.ConnectionError("ollama down"),
        requests.ConnectionError("ollama down"),
    ])
    with pytest.raises(rk.RankerError, match="ollama unreachable"):
        rk.rank_windows(_windows(3), model="m", top_n=2)


def test_unreachable_then_recover(monkeypatch):
    """First call hits a connection error; retry succeeds."""
    good = {"clips": [
        {"candidate_id": "c0", "hook": "h", "suggested_title": "T", "score": 9.0},
        {"candidate_id": "c1", "hook": "h", "suggested_title": "T", "score": 8.0},
    ]}
    _patch_post(monkeypatch, [requests.ConnectionError("blip"), _resp(good)])
    out = rk.rank_windows(_windows(3), model="m", top_n=2)
    assert len(out) == 2


# ---- empty inputs -----------------------------------------------------------


def test_empty_windows_raises():
    with pytest.raises(rk.RankerError, match="no candidate windows"):
        rk.rank_windows([], model="m", top_n=2)
