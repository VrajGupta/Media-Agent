"""Ollama NSFW classifier: parse, retry, fail-soft on infrastructure failures."""

from __future__ import annotations

import json
from types import SimpleNamespace

import requests

from src.policy_gate import nsfw as nsfw_mod


def _resp(content_obj: dict, status: int = 200):
    body = {"message": {"content": json.dumps(content_obj)}}

    def _raise():
        if status >= 400:
            raise requests.HTTPError(f"status={status}")

    return SimpleNamespace(status_code=status, raise_for_status=_raise, json=lambda: body)


def _patch_post(monkeypatch, responses: list):
    calls = {"n": 0}

    def fake_post(url, json=None, timeout=None):
        idx = calls["n"]
        calls["n"] += 1
        item = responses[idx]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(nsfw_mod.requests, "post", fake_post)
    return calls


def test_safe_label_passes(monkeypatch):
    _patch_post(monkeypatch, [_resp({"label": "safe", "score": 0.05, "reason": "ok"})])
    v = nsfw_mod.classify_nsfw("hello world", model="m")
    assert v.label == "safe"
    assert v.is_rejection is False


def test_nsfw_high_score_rejects(monkeypatch):
    _patch_post(monkeypatch, [_resp({"label": "nsfw", "score": 0.91, "reason": "explicit"})])
    v = nsfw_mod.classify_nsfw("clip text", model="m")
    assert v.label == "nsfw"
    assert v.score == 0.91
    assert v.is_rejection is True


def test_nsfw_low_score_does_not_reject(monkeypatch):
    """label='nsfw' but score<0.5 should not reject — model is unsure."""
    _patch_post(monkeypatch, [_resp({"label": "nsfw", "score": 0.30, "reason": "marginal"})])
    v = nsfw_mod.classify_nsfw("clip text", model="m")
    assert v.label == "nsfw"
    assert v.is_rejection is False


def test_malformed_json_retries_then_recovers(monkeypatch):
    """First response is invalid JSON; retry returns valid output."""
    bad = SimpleNamespace(
        status_code=200,
        raise_for_status=lambda: None,
        json=lambda: {"message": {"content": "{not json"}},
    )
    good = _resp({"label": "safe", "score": 0.1, "reason": "ok"})
    calls = _patch_post(monkeypatch, [bad, good])
    v = nsfw_mod.classify_nsfw("clip text", model="m")
    assert v.label == "safe"
    assert calls["n"] == 2


def test_network_failure_after_retry_returns_infrastructure_failed(monkeypatch):
    _patch_post(monkeypatch, [
        requests.ConnectionError("blip"),
        requests.ConnectionError("blip"),
    ])
    v = nsfw_mod.classify_nsfw("clip text", model="m")
    assert v.label == "infrastructure_failed"
    assert v.is_rejection is False


def test_unknown_label_after_retry_returns_infrastructure_failed(monkeypatch):
    """Contract failure (unknown label) is a fail-soft: same path as malformed JSON.

    Per the plan: we never reject content because of an Ollama bug.
    """
    bad = _resp({"label": "maybe", "score": 0.5, "reason": "?"})
    _patch_post(monkeypatch, [bad, bad])
    v = nsfw_mod.classify_nsfw("clip text", model="m")
    assert v.label == "infrastructure_failed"
    assert v.is_rejection is False
