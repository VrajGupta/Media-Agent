"""Ollama zero-shot NSFW transcript classifier.

Mirrors the pattern in src/selector/ranker.py: POST /api/chat with
format=json, fixed system prompt for prefix-cache reuse, one retry on
malformed JSON / network error.

Returns an NsfwVerdict dataclass that the policy evaluator interprets.
The "infrastructure_failed" branch is handled by the evaluator (fail-soft:
leave clip at 'selected', alert at run end).
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
    "You are a content moderation classifier for a YouTube Shorts channel. "
    "Given a clip transcript, decide whether the content is NSFW. "
    "NSFW examples: explicit sexual content, graphic violence with gore, "
    "explicit drug use instructions, hate speech, self-harm encouragement. "
    "Strong language alone is NOT NSFW. Mature themes discussed analytically "
    "are NOT NSFW. Return JSON only. Schema: "
    '{"label": "safe"|"nsfw", "score": <0.0..1.0 confidence>, '
    '"reason": "<one short phrase>"}.'
)


@dataclass
class NsfwVerdict:
    label: str          # "safe" | "nsfw" | "infrastructure_failed"
    score: float        # 0.0..1.0; meaningless when infrastructure_failed
    reason: str
    is_rejection: bool  # convenience: label=='nsfw' AND score>=0.5


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


def _parse_response(response: dict) -> tuple[str, float, str]:
    """Returns (label, score, reason). Raises ValueError on contract failure."""
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
    label = parsed.get("label")
    if label not in ("safe", "nsfw"):
        raise ValueError(f"unknown label: {label!r}")
    try:
        score = float(parsed.get("score", 0.0))
    except (TypeError, ValueError):
        raise ValueError(f"score not a number: {parsed.get('score')!r}")
    reason = str(parsed.get("reason") or "")
    return (label, score, reason)


def classify_nsfw(
    clip_text: str,
    *,
    model: str,
    host: Optional[str] = None,
) -> NsfwVerdict:
    """One Ollama call, one retry. Never raises; on persistent failure
    returns label='infrastructure_failed' so the caller can fail-soft.
    """
    if not clip_text or not clip_text.strip():
        return NsfwVerdict(label="safe", score=0.0, reason="empty text", is_rejection=False)

    host = (host or _ollama_host()).rstrip("/")
    user_prompt = f"Clip transcript:\n{clip_text}\n\nReturn STRICT JSON."

    last_error: Optional[Exception] = None
    for attempt in (1, 2):
        try:
            response = _post_chat(model, user_prompt, host)
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            logger.warning(f"nsfw ollama HTTP error (attempt {attempt}): {exc}")
            if attempt == 2:
                return NsfwVerdict(
                    label="infrastructure_failed",
                    score=0.0,
                    reason=f"ollama unreachable: {exc}",
                    is_rejection=False,
                )
            continue

        try:
            label, score, reason = _parse_response(response)
        except ValueError as exc:
            last_error = exc
            logger.warning(f"nsfw ollama output invalid (attempt {attempt}): {exc}")
            user_prompt = (
                f"Clip transcript:\n{clip_text}\n\n"
                f"IMPORTANT: previous response was invalid: {exc}. "
                f'Return STRICT JSON: {{"label":"safe"|"nsfw","score":0.0..1.0,"reason":"..."}}.'
            )
            continue

        # Reject only on high-confidence NSFW (>0.85). qwen2.5:3b returns
        # 0.6-0.85 on borderline content (trauma discussion, casual drug
        # mentions in podcasts) with high run-to-run variance, while genuine
        # explicit content scores 0.9+ deterministically. The strictly-greater
        # boundary at 0.85 was chosen empirically during Phase 4.5 live
        # verification: borderline content maxes at 0.85, genuine NSFW starts
        # at 0.9. Lets standard mature-but-publishable Joe Rogan content
        # through while catching graphic sexual / self-harm / hate-speech.
        is_rejection = (label == "nsfw" and score > 0.85)
        return NsfwVerdict(label=label, score=score, reason=reason, is_rejection=is_rejection)

    return NsfwVerdict(
        label="infrastructure_failed",
        score=0.0,
        reason=f"invalid output after retry: {last_error}",
        is_rejection=False,
    )
