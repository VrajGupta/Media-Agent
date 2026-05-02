"""Pure policy evaluator: short-circuit + no DB / file I/O."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.policy_gate import evaluator as ev_mod
from src.policy_gate.evaluator import evaluate_clip_policy
from src.policy_gate.hook_sanity import HookSanityVerdict
from src.policy_gate.nsfw import NsfwVerdict
from src.policy_gate.topic_filter import TopicVerdict


def _allow_topic(monkeypatch):
    """Helper: stub topic_filter to return 'allowed' for tests that don't
    care about that check (so Ollama isn't called for real)."""
    monkeypatch.setattr(
        ev_mod.topic_mod, "classify_topic",
        lambda *a, **kw: TopicVerdict(verdict="allowed", reason="", infrastructure_failed=False),
    )


@pytest.fixture
def cfg_stub():
    return SimpleNamespace(
        banlist=["suicide", "self-harm"],
        profanity_max_score=5,
        hook_sanity_min_score=3,
        ollama_model="qwen2.5:3b-instruct",
    )


def test_banlist_short_circuits_before_ollama(monkeypatch, cfg_stub):
    """A banlist hit must skip ALL three Ollama calls entirely (nsfw,
    hook_sanity, topic_filter)."""
    nsfw_called = {"count": 0}
    hook_called = {"count": 0}
    topic_called = {"count": 0}

    def fake_nsfw(*a, **kw):
        nsfw_called["count"] += 1
        return NsfwVerdict(label="safe", score=0.0, reason="", is_rejection=False)

    def fake_hook(*a, **kw):
        hook_called["count"] += 1
        return HookSanityVerdict(accepted=True, reason="", infrastructure_failed=False)

    def fake_topic(*a, **kw):
        topic_called["count"] += 1
        return TopicVerdict(verdict="allowed", reason="", infrastructure_failed=False)

    monkeypatch.setattr(ev_mod.nsfw_mod, "classify_nsfw", fake_nsfw)
    monkeypatch.setattr(ev_mod.hook_mod, "rate_hook_sanity", fake_hook)
    monkeypatch.setattr(ev_mod.topic_mod, "classify_topic", fake_topic)

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
    assert topic_called["count"] == 0


def test_all_pass_runs_every_check(monkeypatch, cfg_stub):
    nsfw_called = {"count": 0}
    hook_called = {"count": 0}
    topic_called = {"count": 0}

    def fake_nsfw(*a, **kw):
        nsfw_called["count"] += 1
        return NsfwVerdict(label="safe", score=0.05, reason="ok", is_rejection=False)

    def fake_hook(*a, **kw):
        hook_called["count"] += 1
        return HookSanityVerdict(accepted=True, reason="ok", infrastructure_failed=False)

    def fake_topic(*a, **kw):
        topic_called["count"] += 1
        return TopicVerdict(verdict="allowed", reason="tech podcast", infrastructure_failed=False)

    monkeypatch.setattr(ev_mod.nsfw_mod, "classify_nsfw", fake_nsfw)
    monkeypatch.setattr(ev_mod.hook_mod, "rate_hook_sanity", fake_hook)
    monkeypatch.setattr(ev_mod.topic_mod, "classify_topic", fake_topic)

    verdict = evaluate_clip_policy(
        cfg_stub,
        clip_text="hello world this is a perfectly clean clip with words",
        suggested_title="A Clean Title",
    )
    assert verdict.passed is True
    assert verdict.failed_check is None
    assert nsfw_called["count"] == 1
    assert hook_called["count"] == 1
    assert topic_called["count"] == 1
    # Verify the per-check trace is populated for diagnostics.
    names = [c.name for c in verdict.checks]
    assert names == ["banlist", "profanity", "nsfw", "hook_sanity", "topic_filter"]
    assert all(c.passed for c in verdict.checks)


def test_topic_filter_religion_rejects(monkeypatch, cfg_stub):
    """Clip topic='religion' rejects with reason 'topic_filter:religion'."""
    monkeypatch.setattr(
        ev_mod.nsfw_mod, "classify_nsfw",
        lambda *a, **kw: NsfwVerdict(label="safe", score=0.05, reason="", is_rejection=False),
    )
    monkeypatch.setattr(
        ev_mod.hook_mod, "rate_hook_sanity",
        lambda *a, **kw: HookSanityVerdict(accepted=True, reason="", infrastructure_failed=False),
    )
    monkeypatch.setattr(
        ev_mod.topic_mod, "classify_topic",
        lambda *a, **kw: TopicVerdict(verdict="religion", reason="discusses prayer", infrastructure_failed=False),
    )

    verdict = evaluate_clip_policy(
        cfg_stub,
        clip_text="discussing the role of prayer in daily life",
        suggested_title="On Faith",
    )
    assert verdict.passed is False
    assert verdict.failed_check == "topic_filter"
    assert verdict.failed_value == "religion"
    assert verdict.reason_string == "topic_filter:religion"


def test_topic_filter_war_rejects(monkeypatch, cfg_stub):
    """Clip topic='war' rejects with reason 'topic_filter:war'."""
    monkeypatch.setattr(
        ev_mod.nsfw_mod, "classify_nsfw",
        lambda *a, **kw: NsfwVerdict(label="safe", score=0.05, reason="", is_rejection=False),
    )
    monkeypatch.setattr(
        ev_mod.hook_mod, "rate_hook_sanity",
        lambda *a, **kw: HookSanityVerdict(accepted=True, reason="", infrastructure_failed=False),
    )
    monkeypatch.setattr(
        ev_mod.topic_mod, "classify_topic",
        lambda *a, **kw: TopicVerdict(verdict="war", reason="Iraq combat operations", infrastructure_failed=False),
    )

    verdict = evaluate_clip_policy(
        cfg_stub,
        clip_text="describing combat operations in Fallujah",
        suggested_title="Frontline",
    )
    assert verdict.passed is False
    assert verdict.failed_check == "topic_filter"
    assert verdict.failed_value == "war"


def test_topic_filter_infrastructure_failure_propagates(monkeypatch, cfg_stub):
    """topic_filter Ollama failure → verdict.infrastructure_failed=True."""
    monkeypatch.setattr(
        ev_mod.nsfw_mod, "classify_nsfw",
        lambda *a, **kw: NsfwVerdict(label="safe", score=0.05, reason="", is_rejection=False),
    )
    monkeypatch.setattr(
        ev_mod.hook_mod, "rate_hook_sanity",
        lambda *a, **kw: HookSanityVerdict(accepted=True, reason="", infrastructure_failed=False),
    )
    monkeypatch.setattr(
        ev_mod.topic_mod, "classify_topic",
        lambda *a, **kw: TopicVerdict(
            verdict="allowed",  # fail-soft default
            reason="ollama unreachable",
            infrastructure_failed=True,
        ),
    )

    verdict = evaluate_clip_policy(cfg_stub, clip_text="hello", suggested_title="Title")
    assert verdict.passed is False
    assert verdict.infrastructure_failed is True
    assert "topic_filter" in (verdict.infrastructure_reason or "")
    assert verdict.failed_check is None  # NOT a content rejection


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
    # hook_sanity and topic_filter should not be called once nsfw fails.
    monkeypatch.setattr(
        ev_mod.hook_mod, "rate_hook_sanity",
        lambda *a, **kw: pytest.fail("hook_sanity should not be called"),
    )
    monkeypatch.setattr(
        ev_mod.topic_mod, "classify_topic",
        lambda *a, **kw: pytest.fail("topic_filter should not be called"),
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
