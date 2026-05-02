"""Pure policy evaluator (Phase 4.5).

Used by the stateful runner (post-select gate) AND by Phase 5's pre-upload
re-check. No DB writes, no file I/O beyond Ollama HTTP. Returns a structured
verdict; the caller decides what to do with it.

Order of checks (short-circuit on first failure):
  1. banlist     — substring match against cfg.banlist
  2. profanity   — better-profanity score > cfg.profanity_max_score
  3. nsfw        — Ollama: label='nsfw' AND score>=0.5
  4. hook_sanity — Ollama: score < cfg.hook_sanity_min_score

Infrastructure failures (Ollama unreachable, malformed output, unknown labels
after retry) bubble up via PolicyVerdict.infrastructure_failed=True so the
caller can fail-soft (leave clip at 'selected' and alert) rather than reject
content because of a flaky model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from src.policy_gate import banlist as banlist_mod
from src.policy_gate import hook_sanity as hook_mod
from src.policy_gate import nsfw as nsfw_mod
from src.policy_gate import profanity as profanity_mod


@dataclass
class CheckResult:
    name: str           # banlist | profanity | nsfw | hook_sanity
    passed: bool
    value: str          # printable value (term, score, label:score, score)
    reason: str = ""    # checker-supplied free-form reason


@dataclass
class PolicyVerdict:
    passed: bool
    failed_check: Optional[str] = None
    failed_value: Optional[str] = None
    infrastructure_failed: bool = False
    infrastructure_reason: Optional[str] = None
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def reason_string(self) -> str:
        """Format used by gate_one_clip when writing rejection_reason."""
        if not self.failed_check:
            return ""
        return f"{self.failed_check}:{self.failed_value}"


class _ConfigLike(Protocol):
    banlist: list[str]
    profanity_max_score: int
    hook_sanity_min_score: int
    ollama_model: str


def evaluate_clip_policy(
    cfg: _ConfigLike,
    clip_text: str,
    suggested_title: str,
    *,
    ollama_host: Optional[str] = None,
) -> PolicyVerdict:
    """Run the four content checks in order. Short-circuit on first content
    failure. Infrastructure failures (NSFW/hook_sanity Ollama) abort with
    infrastructure_failed=True; the caller fails-soft.
    """
    checks: list[CheckResult] = []

    # 1. banlist — concatenate clip text + title.
    haystack = (clip_text + " " + (suggested_title or "")).strip()
    term = banlist_mod.find_banlisted_term(haystack, cfg.banlist or [])
    if term is not None:
        checks.append(CheckResult(name="banlist", passed=False, value=term))
        return PolicyVerdict(
            passed=False,
            failed_check="banlist",
            failed_value=term,
            checks=checks,
        )
    checks.append(CheckResult(name="banlist", passed=True, value="-"))

    # 2. profanity — clip text + title.
    prof_text = haystack
    over, score = profanity_mod.is_profane(prof_text, float(cfg.profanity_max_score))
    score_str = f"{score:.1f}"
    if over:
        checks.append(CheckResult(name="profanity", passed=False, value=score_str))
        return PolicyVerdict(
            passed=False,
            failed_check="profanity",
            failed_value=score_str,
            checks=checks,
        )
    checks.append(CheckResult(name="profanity", passed=True, value=score_str))

    # 3. nsfw — Ollama call. Empty-text edge already returns 'safe' upstream.
    nsfw_verdict = nsfw_mod.classify_nsfw(
        clip_text,
        model=cfg.ollama_model,
        host=ollama_host,
    )
    if nsfw_verdict.label == "infrastructure_failed":
        return PolicyVerdict(
            passed=False,
            infrastructure_failed=True,
            infrastructure_reason=f"nsfw:{nsfw_verdict.reason}",
            checks=checks,
        )
    nsfw_value = f"{nsfw_verdict.score:.2f}"
    if nsfw_verdict.is_rejection:
        checks.append(CheckResult(
            name="nsfw", passed=False, value=nsfw_value, reason=nsfw_verdict.reason,
        ))
        return PolicyVerdict(
            passed=False,
            failed_check="nsfw",
            failed_value=nsfw_value,
            checks=checks,
        )
    checks.append(CheckResult(
        name="nsfw", passed=True, value=nsfw_value, reason=nsfw_verdict.reason,
    ))

    # 4. hook_sanity — Ollama call.
    hook_verdict = hook_mod.rate_hook_sanity(
        clip_text,
        suggested_title or "",
        model=cfg.ollama_model,
        host=ollama_host,
    )
    if hook_verdict.infrastructure_failed:
        return PolicyVerdict(
            passed=False,
            infrastructure_failed=True,
            infrastructure_reason=f"hook_sanity:{hook_verdict.reason}",
            checks=checks,
        )
    hook_value = str(hook_verdict.score)
    if hook_verdict.score < cfg.hook_sanity_min_score:
        checks.append(CheckResult(
            name="hook_sanity", passed=False, value=hook_value, reason=hook_verdict.reason,
        ))
        return PolicyVerdict(
            passed=False,
            failed_check="hook_sanity",
            failed_value=hook_value,
            checks=checks,
        )
    checks.append(CheckResult(
        name="hook_sanity", passed=True, value=hook_value, reason=hook_verdict.reason,
    ))

    return PolicyVerdict(passed=True, checks=checks)
