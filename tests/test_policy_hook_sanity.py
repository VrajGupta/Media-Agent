"""Ollama hook-sanity rater (binary accept/reject)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import requests

from src.policy_gate import hook_sanity as hook_mod


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

    monkeypatch.setattr(hook_mod.requests, "post", fake_post)
    return calls


def test_accept_verdict_passes(monkeypatch):
    _patch_post(monkeypatch, [_resp({"verdict": "accept", "reason": "topic matches"})])
    v = hook_mod.rate_hook_sanity("clip text", "Great Title", model="m")
    assert v.accepted is True
    assert v.infrastructure_failed is False
    assert "topic matches" in v.reason


def test_reject_verdict_returned_as_is(monkeypatch):
    """The rater only reports the verdict; rejection logic is in the evaluator."""
    _patch_post(monkeypatch, [_resp({"verdict": "reject", "reason": "topic mismatch"})])
    v = hook_mod.rate_hook_sanity("clip text", "Click bait!", model="m")
    assert v.accepted is False
    assert v.infrastructure_failed is False


def test_malformed_json_retries(monkeypatch):
    bad = SimpleNamespace(
        status_code=200,
        raise_for_status=lambda: None,
        json=lambda: {"message": {"content": "{not json"}},
    )
    good = _resp({"verdict": "accept", "reason": "ok"})
    calls = _patch_post(monkeypatch, [bad, good])
    v = hook_mod.rate_hook_sanity("clip text", "Title", model="m")
    assert v.accepted is True
    assert calls["n"] == 2


def test_network_failure_returns_infrastructure_failed(monkeypatch):
    _patch_post(monkeypatch, [
        requests.ConnectionError("down"),
        requests.ConnectionError("down"),
    ])
    v = hook_mod.rate_hook_sanity("clip text", "Title", model="m")
    assert v.infrastructure_failed is True
    assert v.accepted is False


def test_unknown_verdict_after_retry_is_infrastructure_failure(monkeypatch):
    """Verdict strings other than accept/reject are contract failures.

    Same path as malformed JSON: retry once, then fail-soft. We never reject
    content because of an Ollama bug.
    """
    bad = _resp({"verdict": "maybe", "reason": "out of range"})
    _patch_post(monkeypatch, [bad, bad])
    v = hook_mod.rate_hook_sanity("clip text", "Title", model="m")
    assert v.infrastructure_failed is True


def test_empty_inputs_short_circuit_to_infrastructure_failed(monkeypatch):
    """Empty clip text or title can't be rated meaningfully — fail-soft."""
    # No HTTP call at all.
    calls = _patch_post(monkeypatch, [requests.ConnectionError("should not be called")])
    v = hook_mod.rate_hook_sanity("", "Some Title", model="m")
    assert v.infrastructure_failed is True
    assert calls["n"] == 0
    v2 = hook_mod.rate_hook_sanity("clip text", "", model="m")
    assert v2.infrastructure_failed is True
    assert calls["n"] == 0
