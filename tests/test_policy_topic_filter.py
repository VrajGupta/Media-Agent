"""Ollama topic_filter classifier (binary religion/war/allowed)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import requests

from src.policy_gate import topic_filter as topic_mod


def _resp(content_obj: dict, status: int = 200):
    body = {"message": {"content": json.dumps(content_obj)}}

    def _raise():
        if status >= 400:
            raise requests.HTTPError(f"status={status}")

    return SimpleNamespace(status_code=status, raise_for_status=_raise, json=lambda: body)


def _patch_post(monkeypatch, responses):
    calls = {"n": 0}

    def fake_post(url, json=None, timeout=None):
        idx = calls["n"]
        calls["n"] += 1
        item = responses[idx]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(topic_mod.requests, "post", fake_post)
    return calls


def test_allowed_verdict_passes(monkeypatch):
    _patch_post(monkeypatch, [_resp({"verdict": "allowed", "reason": "tech podcast"})])
    v = topic_mod.classify_topic("clip about AI music recognition", model="m")
    assert v.verdict == "allowed"
    assert v.is_rejection is False
    assert v.infrastructure_failed is False


def test_religion_verdict_rejects(monkeypatch):
    _patch_post(monkeypatch, [_resp({"verdict": "religion", "reason": "discusses prayer"})])
    v = topic_mod.classify_topic("clip text about prayer", model="m")
    assert v.verdict == "religion"
    assert v.is_rejection is True


def test_war_verdict_rejects(monkeypatch):
    _patch_post(monkeypatch, [_resp({"verdict": "war", "reason": "Iraq War combat"})])
    v = topic_mod.classify_topic("clip about combat operations", model="m")
    assert v.verdict == "war"
    assert v.is_rejection is True


def test_malformed_json_retries(monkeypatch):
    bad = SimpleNamespace(
        status_code=200,
        raise_for_status=lambda: None,
        json=lambda: {"message": {"content": "{not json"}},
    )
    good = _resp({"verdict": "allowed", "reason": "ok"})
    calls = _patch_post(monkeypatch, [bad, good])
    v = topic_mod.classify_topic("clip text", model="m")
    assert v.verdict == "allowed"
    assert v.is_rejection is False
    assert calls["n"] == 2


def test_network_failure_fails_soft_to_allowed(monkeypatch):
    """Per the plan: never reject content because of an Ollama bug.
    Persistent network failure → fail-soft, treated as 'allowed' so the
    runner won't reject — but infrastructure_failed=True flag bubbles up."""
    _patch_post(monkeypatch, [
        requests.ConnectionError("down"),
        requests.ConnectionError("down"),
    ])
    v = topic_mod.classify_topic("clip text", model="m")
    assert v.infrastructure_failed is True
    assert v.verdict == "allowed"
    assert v.is_rejection is False


def test_unknown_verdict_after_retry_is_infrastructure_failure(monkeypatch):
    """Verdict strings other than allowed/religion/war are contract failures."""
    bad = _resp({"verdict": "neutral", "reason": "?"})
    _patch_post(monkeypatch, [bad, bad])
    v = topic_mod.classify_topic("clip text", model="m")
    assert v.infrastructure_failed is True
    assert v.is_rejection is False


def test_empty_clip_text_is_allowed_no_http_call(monkeypatch):
    """Empty input is treated as allowed without spawning an Ollama call."""
    calls = _patch_post(monkeypatch, [requests.ConnectionError("should not be called")])
    v = topic_mod.classify_topic("", model="m")
    assert v.verdict == "allowed"
    assert calls["n"] == 0
