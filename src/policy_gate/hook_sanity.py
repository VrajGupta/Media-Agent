"""Ollama hook-sanity rater: does the suggested title accurately summarize
the clip transcript? Returns a binary accept/reject verdict.

Why binary instead of 1-5 ordinal?
qwen2.5:3b-instruct (locked Phase 0 model) cannot calibrate a 1-5 rubric —
it consistently returns 1 for ALL inputs regardless of title quality
(empirically verified during Phase 4.5 live verification: a perfect-summary
title and a topic-mismatch title both scored 1). Small models do binary
classification well, so we ask: "is this title accurate enough to publish,
or does it misrepresent the clip's subject?"

We reject only when the title is about a DIFFERENT topic than the clip
(e.g. clip about books, title about crypto). Aggressive/clickbait phrasing
that nonetheless points at the right subject is accepted — that's standard
YouTube Shorts style.

Mirror of src/selector/ranker.py / src/policy_gate/nsfw.py: one HTTP call
per clip, one retry on malformed JSON, fail-soft on persistent infrastructure
failure (the runner leaves the clip at 'selected' and alerts).
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
    "You decide whether a clip title is accurate enough to publish on a "
    "YouTube Shorts repost channel.\n"
    "Reject ONLY if the title misrepresents the clip's actual subject "
    "(e.g. title is about crypto but clip is about books).\n"
    "Accept aggressive/clickbait phrasing as long as the topic matches.\n"
    'Return JSON only: {"verdict": "accept" or "reject", '
    '"reason": "<one short phrase>"}.'
)


@dataclass
class HookSanityVerdict:
    accepted: bool                  # True = title matches clip topic
    reason: str
    infrastructure_failed: bool     # True iff persistent Ollama failure


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


def _parse_response(response: dict) -> tuple[bool, str]:
    """Returns (accepted, reason). Raises ValueError on contract failure."""
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
    raw_verdict = parsed.get("verdict")
    if not isinstance(raw_verdict, str):
        raise ValueError(f"verdict not a string: {raw_verdict!r}")
    v = raw_verdict.strip().lower()
    if v.startswith("acc"):
        accepted = True
    elif v.startswith("rej"):
        accepted = False
    else:
        raise ValueError(f"unknown verdict: {raw_verdict!r}")
    reason = str(parsed.get("reason") or "")
    return (accepted, reason)


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
            accepted=False,
            reason="empty input",
            infrastructure_failed=True,
        )

    host = (host or _ollama_host()).rstrip("/")
    user_prompt = (
        f'Title: "{suggested_title}"\n\n'
        f"Clip transcript:\n{clip_text}\n\n"
        "Return JSON."
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
                    accepted=False,
                    reason=f"ollama unreachable: {exc}",
                    infrastructure_failed=True,
                )
            continue

        try:
            accepted, reason = _parse_response(response)
        except ValueError as exc:
            last_error = exc
            logger.warning(f"hook_sanity ollama output invalid (attempt {attempt}): {exc}")
            user_prompt = (
                f'Title: "{suggested_title}"\n\n'
                f"Clip transcript:\n{clip_text}\n\n"
                f"IMPORTANT: previous response was invalid: {exc}. "
                'Return STRICT JSON: {"verdict": "accept" or "reject", "reason": "..."}.'
            )
            continue

        return HookSanityVerdict(
            accepted=accepted,
            reason=reason,
            infrastructure_failed=False,
        )

    return HookSanityVerdict(
        accepted=False,
        reason=f"invalid output after retry: {last_error}",
        infrastructure_failed=True,
    )
