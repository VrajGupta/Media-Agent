"""Pure policy evaluator: short-circuit + no DB / file I/O."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.policy_gate import evaluator as ev_mod
from src.policy_gate.evaluator import evaluate_clip_policy
from src.policy_gate.hook_sanity import HookSanityVerdict
from src.policy_gate.nsfw import NsfwVerdict


@pytest.fixture
def cfg_stub():
    return SimpleNamespace(
        banlist=["suicide", "self-harm"],
        profanity_max_score=5,
        hook_sanity_min_score=3,
        ollama_model="qwen2.5:3b-instruct",
    )


def test_banlist_short_circuits_before_ollama(monkeypatch, cfg_stub):
    """A banlist hit must skip the NSFW + hook_sanity Ollama calls entirely."""
    nsfw_called = {"count": 0}
    hook_called = {"count": 0}

    def fake_nsfw(*a, **kw):
        nsfw_called["count"] += 1
        return NsfwVerdict(label="safe", score=0.0, reason="", is_rejection=False)

    def fake_hook(*a, **kw):
        hook_called["count"] += 1
        return HookSanityVerdict(score=5, reason="", infrastructure_failed=False)

    monkeypatch.setattr(ev_mod.nsfw_mod, "classify_nsfw", fake_nsfw)
    monkeypatch.setattr(ev_mod.hook_mod, "rate_hook_sanity", fake_hook)

    verdict = evaluate_clip_policy(
        cfg_stub,
        clip_text="we should talk about suicide today",
        suggested_title="Mental Health",
    )
    assert verdict.passed is False
    assert verdict.failed_check == "banlist"
    assert verdict.failed_value == "suicide"
    assert verdict.reason_string == "banlist:suicide"
    assert nsfw_called["count"] == 0
    assert hook_called["count"] == 0


def test_all_pass_runs_every_check(monkeypatch, cfg_stub):
    nsfw_called = {"count": 0}
    hook_called = {"count": 0}

    def fake_nsfw(*a, **kw):
        nsfw_called["count"] += 1
        return NsfwVerdict(label="safe", score=0.05, reason="ok", is_rejection=False)

    def fake_hook(*a, **kw):
        hook_called["count"] += 1
        return HookSanityVerdict(score=4, reason="ok", infrastructure_failed=False)

    monkeypatch.setattr(ev_mod.nsfw_mod, "classify_nsfw", fake_nsfw)
    monkeypatch.setattr(ev_mod.hook_mod, "rate_hook_sanity", fake_hook)

    verdict = evaluate_clip_policy(
        cfg_stub,
        clip_text="hello world this is a perfectly clean clip with words",
        suggested_title="A Clean Title",
    )
    assert verdict.passed is True
    assert verdict.failed_check is None
    assert nsfw_called["count"] == 1
    assert hook_called["count"] == 1
    # Verify the per-check trace is populated for diagnostics.
    names = [c.name for c in verdict.checks]
    assert names == ["banlist", "profanity", "nsfw", "hook_sanity"]
    assert all(c.passed for c in verdict.checks)


def test_nsfw_infrastructure_failure_propagates(monkeypatch, cfg_stub):
    """Ollama infrastructure failure → verdict.infrastructure_failed=True;
    runner uses this to fail-soft (leave clip at 'selected').
    """
    monkeypatch.setattr(
        ev_mod.nsfw_mod, "classify_nsfw",
        lambda *a, **kw: NsfwVerdict(
            label="infrastructure_failed", score=0.0,
            reason="ollama unreachable", is_rejection=False,
        ),
    )
    # hook_sanity should not be called once nsfw fails infrastructure.
    monkeypatch.setattr(
        ev_mod.hook_mod, "rate_hook_sanity",
        lambda *a, **kw: pytest.fail("hook_sanity should not be called"),
    )

    verdict = evaluate_clip_policy(
        cfg_stub,
        clip_text="hello world",
        suggested_title="Title",
    )
    assert verdict.passed is False
    assert verdict.infrastructure_failed is True
    assert "nsfw" in (verdict.infrastructure_reason or "")
    assert verdict.failed_check is None  # NOT a content rejection
