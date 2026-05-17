"""Verify that evaluate_clip_policy accepts injectable classifier functions.

After P3 the callers no longer need monkeypatch — they pass fake callables directly.
These tests replace the monkeypatch pattern in test_policy_evaluator.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.policy_gate.evaluator import evaluate_clip_policy
from src.policy_gate.hook_sanity import HookSanityVerdict
from src.policy_gate.nsfw import NsfwVerdict
from src.policy_gate.topic_filter import TopicVerdict


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------

def _safe_nsfw(text: str) -> NsfwVerdict:
    return NsfwVerdict(label="safe", score=0.05, reason="ok", is_rejection=False)

def _accept_hook(text: str, title: str) -> HookSanityVerdict:
    return HookSanityVerdict(accepted=True, reason="ok", infrastructure_failed=False)

def _allow_topic(text: str) -> TopicVerdict:
    return TopicVerdict(verdict="allowed", reason="ok", infrastructure_failed=False)

def _reject_nsfw(text: str) -> NsfwVerdict:
    return NsfwVerdict(label="nsfw", score=0.95, reason="explicit", is_rejection=True)

def _reject_hook(text: str, title: str) -> HookSanityVerdict:
    return HookSanityVerdict(accepted=False, reason="topic mismatch", infrastructure_failed=False)

def _reject_topic(text: str) -> TopicVerdict:
    return TopicVerdict(verdict="religion", reason="primarily about prayer", infrastructure_failed=False)

def _infra_failed_nsfw(text: str) -> NsfwVerdict:
    return NsfwVerdict(label="infrastructure_failed", score=0.0, reason="ollama unreachable", is_rejection=False)


@pytest.fixture
def cfg():
    return SimpleNamespace(
        banlist=["suicide", "self-harm"],
        profanity_max_score=5,
        hook_sanity_min_score=3,
        ollama_model="qwen2.5:3b-instruct",
    )


# ---------------------------------------------------------------------------
# Injection works — no monkeypatch needed
# ---------------------------------------------------------------------------


def test_all_pass_via_injection(cfg):
    verdict = evaluate_clip_policy(
        cfg,
        clip_text="a weird fact about deep sea creatures",
        suggested_title="Deep Sea Facts",
        nsfw_fn=_safe_nsfw,
        hook_fn=_accept_hook,
        topic_fn=_allow_topic,
    )
    assert verdict.passed is True
    assert verdict.failed_check is None


def test_nsfw_rejection_via_injection(cfg):
    verdict = evaluate_clip_policy(
        cfg,
        clip_text="some content",
        suggested_title="Title",
        nsfw_fn=_reject_nsfw,
        hook_fn=_accept_hook,
        topic_fn=_allow_topic,
    )
    assert verdict.passed is False
    assert verdict.failed_check == "nsfw"


def test_hook_rejection_via_injection(cfg):
    verdict = evaluate_clip_policy(
        cfg,
        clip_text="clip about biology",
        suggested_title="Title about crypto",
        nsfw_fn=_safe_nsfw,
        hook_fn=_reject_hook,
        topic_fn=_allow_topic,
    )
    assert verdict.passed is False
    assert verdict.failed_check == "hook_sanity"


def test_topic_rejection_via_injection(cfg):
    verdict = evaluate_clip_policy(
        cfg,
        clip_text="discussing the role of prayer in daily life",
        suggested_title="On Faith",
        nsfw_fn=_safe_nsfw,
        hook_fn=_accept_hook,
        topic_fn=_reject_topic,
    )
    assert verdict.passed is False
    assert verdict.failed_check == "topic_filter"
    assert verdict.failed_value == "religion"


def test_nsfw_infra_failure_via_injection(cfg):
    verdict = evaluate_clip_policy(
        cfg,
        clip_text="hello world",
        suggested_title="Title",
        nsfw_fn=_infra_failed_nsfw,
        hook_fn=_accept_hook,
        topic_fn=_allow_topic,
    )
    assert verdict.passed is False
    assert verdict.infrastructure_failed is True
    assert verdict.failed_check is None


def test_banlist_still_short_circuits_before_any_fn_called(cfg):
    """Banlist hit must not call any injectable fn — they're after it in order."""
    nsfw_called = {"n": 0}

    def tracking_nsfw(text):
        nsfw_called["n"] += 1
        return _safe_nsfw(text)

    verdict = evaluate_clip_policy(
        cfg,
        clip_text="we should talk about suicide today",
        suggested_title="Mental Health",
        nsfw_fn=tracking_nsfw,
        hook_fn=_accept_hook,
        topic_fn=_allow_topic,
    )
    assert verdict.passed is False
    assert verdict.failed_check == "banlist"
    assert nsfw_called["n"] == 0


def test_ollama_host_param_no_longer_accepted(cfg):
    """ollama_host must NOT be a parameter — it was removed in P3."""
    import inspect
    sig = inspect.signature(evaluate_clip_policy)
    assert "ollama_host" not in sig.parameters
