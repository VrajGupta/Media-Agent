"""Ollama hook-sanity rater: does the suggested title accurately summarize
the clip transcript? Score 1..5. Reject if score < cfg.hook_sanity_min_score.

Mirrors src/selector/ranker.py / src/policy_gate/nsfw.py: one call per clip,
one retry on malformed output, fail-soft on persistent infrastructure failure.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

import requests
from loguru import logger

DEFAULT_HOST = "http://localhost:11434"
TIMEOUT_SECONDS = 60.0
KEEP_ALIVE = "10m"

SYSTEM_PROMPT = (
    "You rate how accurately a suggested clip title summarizes a clip's "
    "transcript. Use this rubric:\n"
    "  5 - title is a clear, accurate hook that matches the clip\n"
    "  4 - title matches but is generic or partially off\n"
    "  3 - title is loosely related; viewer would not feel deceived\n"
    "  2 - title overstates or misses the main point\n"
    "  1 - title is misleading clickbait that misrepresents the clip\n"
    "Return JSON only. Schema: "
    '{"score": <integer 1-5>, "reason": "<one short phrase>"}.'
)


@dataclass
class HookSanityVerdict:
    score: int          # 1..5; 0 indicates infrastructure_failed
    reason: str
    infrastructure_failed: bool


def _ollama_host() -> str:
    return os.environ.get("OLLAMA_HOST", DEFAULT_HOST).rstrip("/")


def _post_chat(model: str, user_prompt: str, host: str) -> dict:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "format": "json",
        "stream": False,
        "keep_alive": KEEP_ALIVE,
    }
    resp = requests.post(f"{host}/api/chat", json=body, timeout=TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json()


def _parse_response(response: dict) -> tuple[int, str]:
    try:
        content = response["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"missing message.content: {exc}") from exc
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"content is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"top-level JSON is not an object: {type(parsed).__name__}")
    raw_score = parsed.get("score")
    try:
        score = int(round(float(raw_score)))
    except (TypeError, ValueError):
        raise ValueError(f"score not a number: {raw_score!r}")
    if score < 1 or score > 5:
        raise ValueError(f"score out of range 1..5: {score}")
    reason = str(parsed.get("reason") or "")
    return (score, reason)


def rate_hook_sanity(
    clip_text: str,
    suggested_title: str,
    *,
    model: str,
    host: Optional[str] = None,
) -> HookSanityVerdict:
    """One call, one retry, fail-soft on persistent infrastructure failure."""
    if not clip_text or not clip_text.strip() or not suggested_title.strip():
        # Edge: empty inputs can't be meaningfully rated. Treat as fail-soft
        # rather than a content rejection.
        return HookSanityVerdict(
            score=0,
            reason="empty input",
            infrastructure_failed=True,
        )

    host = (host or _ollama_host()).rstrip("/")
    user_prompt = (
        f'Suggested title: "{suggested_title}"\n\n'
        f"Clip transcript:\n{clip_text}\n\n"
        "Rate 1-5. Return STRICT JSON."
    )

    last_error: Optional[Exception] = None
    for attempt in (1, 2):
        try:
            response = _post_chat(model, user_prompt, host)
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            logger.warning(f"hook_sanity ollama HTTP error (attempt {attempt}): {exc}")
            if attempt == 2:
                return HookSanityVerdict(
                    score=0,
                    reason=f"ollama unreachable: {exc}",
                    infrastructure_failed=True,
                )
            continue

        try:
            score, reason = _parse_response(response)
        except ValueError as exc:
            last_error = exc
            logger.warning(f"hook_sanity ollama output invalid (attempt {attempt}): {exc}")
            user_prompt = (
                f'Suggested title: "{suggested_title}"\n\n'
                f"Clip transcript:\n{clip_text}\n\n"
                f"IMPORTANT: previous response was invalid: {exc}. "
                'Return STRICT JSON: {"score": 1..5, "reason": "..."}.'
            )
            continue

        return HookSanityVerdict(score=score, reason=reason, infrastructure_failed=False)

    return HookSanityVerdict(
        score=0,
        reason=f"invalid output after retry: {last_error}",
        infrastructure_failed=True,
    )
