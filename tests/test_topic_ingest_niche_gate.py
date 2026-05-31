"""Issue 31 — on-niche relevance gate at ingest (mocked Ollama)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import requests

from src.topic_ingest import niche_gate as ng_mod


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

    monkeypatch.setattr(ng_mod.requests, "post", fake_post)
    return calls


def test_onlyfans_apple_tv_story_is_off_niche(monkeypatch):
    _patch_post(monkeypatch, [_resp({"verdict": "off_niche", "reason": "culture entertainment"})])
    v = ng_mod.classify_niche(
        "'It's in the air': Apple TV's hottest new shows explore different sides of OnlyFans",
        "Apple TV culture story about adult-themed shows.",
        model="m",
    )
    assert v.verdict == "off_niche"
    assert v.is_on_niche is False


def test_claude_opus_release_is_on_niche(monkeypatch):
    _patch_post(monkeypatch, [_resp({"verdict": "on_niche", "reason": "major AI model launch"})])
    v = ng_mod.classify_niche(
        "Claude Opus 4.7 released",
        "Anthropic ships its latest frontier model.",
        model="m",
    )
    assert v.verdict == "on_niche"
    assert v.is_on_niche is True


def test_ios_apple_intelligence_is_on_niche(monkeypatch):
    _patch_post(monkeypatch, [_resp({"verdict": "on_niche", "reason": "AI in major OS release"})])
    v = ng_mod.classify_niche(
        "iOS 19 adds Apple Intelligence features",
        "Apple expands on-device AI across the iPhone lineup.",
        model="m",
    )
    assert v.verdict == "on_niche"


def test_startup_funding_is_off_niche(monkeypatch):
    _patch_post(monkeypatch, [_resp({"verdict": "off_niche", "reason": "startup funding"})])
    v = ng_mod.classify_niche(
        "AI startup raises $20M Series B",
        "Another round for a small tooling company.",
        model="m",
    )
    assert v.verdict == "off_niche"


def test_empty_title_is_off_niche_without_http(monkeypatch):
    calls = _patch_post(monkeypatch, [requests.ConnectionError("should not run")])
    v = ng_mod.classify_niche("", "summary", model="m")
    assert v.verdict == "off_niche"
    assert calls["n"] == 0


def test_infra_failure_keeps_topic_and_emits_alert(tmp_path):
    from src.topic_ingest.runner import _apply_niche_gate

    cfg = SimpleNamespace(ollama_model="m")
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    def _classify(_title, _summary, *, model):
        return ng_mod.NicheVerdict(
            verdict="off_niche",
            reason="ollama unreachable",
            infrastructure_failed=True,
        )

    assert _apply_niche_gate(
        "Claude Opus 4.7 released",
        "summary",
        cfg,
        logs_dir=logs_dir,
        _classify=_classify,
    ) is True
    alerts = (logs_dir / "alerts.md").read_text(encoding="utf-8")
    assert "niche_gate_unavailable" in alerts


def test_off_niche_still_dropped():
    from src.topic_ingest.runner import _apply_niche_gate

    cfg = SimpleNamespace(ollama_model="m")

    def _classify(_title, _summary, *, model):
        return ng_mod.NicheVerdict(
            verdict="off_niche",
            reason="culture entertainment",
            infrastructure_failed=False,
        )

    assert _apply_niche_gate("OnlyFans TV show", "summary", cfg, _classify=_classify) is False


def test_on_niche_still_kept():
    from src.topic_ingest.runner import _apply_niche_gate

    cfg = SimpleNamespace(ollama_model="m")

    def _classify(_title, _summary, *, model):
        return ng_mod.NicheVerdict(
            verdict="on_niche",
            reason="major AI model launch",
            infrastructure_failed=False,
        )

    assert _apply_niche_gate("Claude Opus 4.7 released", "summary", cfg, _classify=_classify) is True
