"""Topic-filter classifier (Phase 4.5 follow-up).

User content policy: the YouTube Shorts channel must NOT publish clips that
are primarily about religion or war/military conflict. This is a hard
content rule independent of NSFW (a clip can be 100% safe for kids and
still be primarily about religion / war — both flavors get rejected).

Binary classifier mirrors src/policy_gate/hook_sanity.py: small models do
yes/no labels reliably, where they failed at 1-5 scoring. We ask:
"Is this clip primarily about religion or war?" and reject if so.

Why not just extend the banlist? A keyword list false-positives on metaphors
("spiritual battle", "for god's sake", "weapon of choice"). The Ollama
classifier reads the surrounding context and rejects only when the topic
is genuinely the clip's primary subject.

Fail-soft on infrastructure failures (network, malformed JSON, unknown
verdicts after retry) — never reject content because of an Ollama bug.
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

# Verdicts that the model can return.
ALLOWED_VERDICTS = {"allowed", "religion", "war"}

SYSTEM_PROMPT = (
    "You are a strict content topic classifier for a YouTube Shorts channel "
    "that does NOT publish religious content or war/military content.\n\n"
    "Read the clip transcript and decide:\n\n"
    "Return \"religion\" if the speaker discusses faith, prayer, god/gods, "
    "religious figures (Jesus, Muhammad, Buddha, etc.), religious practices "
    "(praying, meditation as a religious practice, religious rituals), "
    "scripture, theology, salvation, heaven/hell, spirituality, or any "
    "religion (Christianity, Islam, Judaism, Hinduism, Buddhism, etc.). "
    "Personal testimonies about faith count as religion. Quotes from religious "
    "figures count as religion. The ONLY exception is casual idiomatic "
    "exclamations ('oh my god', 'thank god') in otherwise non-religious clips.\n\n"
    "Return \"war\" if the speaker describes war, military operations, "
    "battles, combat, soldiers/marines/troops in active service, weapons of "
    "war (rifles, missiles, bombs, drones), terrorism, military conflict, "
    "or specific wars (Iraq, Vietnam, Ukraine, etc.). Pure metaphorical use "
    "('battle of wits', 'weapon of choice') in non-military contexts does "
    "NOT count.\n\n"
    "Return \"allowed\" for everything else: history (without religion or "
    "war as primary subject), politics, philosophy (including stoicism), "
    "sports, comedy, business, tech, science, true crime, self-improvement, "
    "psychology, music, podcasting, etc.\n\n"
    "When you see religious or military content, even mixed with other "
    "topics, classify it as religion or war. The bar for rejection is "
    "LOW because the channel cannot publish this content.\n"
    'Return JSON only: {"verdict": "allowed" or "religion" or "war", '
    '"reason": "<one short phrase>"}.'
)


@dataclass
class TopicVerdict:
    verdict: str                    # "allowed" | "religion" | "war"
    reason: str
    infrastructure_failed: bool

    @property
    def is_rejection(self) -> bool:
        return self.verdict in ("religion", "war")


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


def _parse_response(response: dict) -> tuple[str, str]:
    """Returns (verdict, reason). Raises ValueError on contract failure."""
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
    if v not in ALLOWED_VERDICTS:
        raise ValueError(f"unknown verdict: {raw_verdict!r}")
    reason = str(parsed.get("reason") or "")
    return (v, reason)


def classify_topic(
    clip_text: str,
    *,
    model: str,
    host: Optional[str] = None,
) -> TopicVerdict:
    """One Ollama call, one retry. Never raises; on persistent failure
    returns infrastructure_failed=True so the caller can fail-soft.
    """
    if not clip_text or not clip_text.strip():
        # Empty input can't be classified meaningfully — treat as allowed.
        return TopicVerdict(
            verdict="allowed",
            reason="empty text",
            infrastructure_failed=False,
        )

    host = (host or _ollama_host()).rstrip("/")
    user_prompt = f"Clip transcript:\n{clip_text}\n\nReturn STRICT JSON."

    last_error: Optional[Exception] = None
    for attempt in (1, 2):
        try:
            response = _post_chat(model, user_prompt, host)
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            logger.warning(f"topic_filter ollama HTTP error (attempt {attempt}): {exc}")
            if attempt == 2:
                return TopicVerdict(
                    verdict="allowed",  # fail-soft = treat as allowed
                    reason=f"ollama unreachable: {exc}",
                    infrastructure_failed=True,
                )
            continue

        try:
            verdict, reason = _parse_response(response)
        except ValueError as exc:
            last_error = exc
            logger.warning(f"topic_filter ollama output invalid (attempt {attempt}): {exc}")
            user_prompt = (
                f"Clip transcript:\n{clip_text}\n\n"
                f"IMPORTANT: previous response was invalid: {exc}. "
                'Return STRICT JSON: {"verdict": "allowed" or "religion" or "war", '
                '"reason": "..."}.'
            )
            continue

        return TopicVerdict(
            verdict=verdict,
            reason=reason,
            infrastructure_failed=False,
        )

    return TopicVerdict(
        verdict="allowed",  # fail-soft
        reason=f"invalid output after retry: {last_error}",
        infrastructure_failed=True,
    )
