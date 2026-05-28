"""On-niche relevance gate at RSS ingest (Issue 31 / ADR-0004)."""

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

ALLOWED_VERDICTS = {"on_niche", "off_niche"}

SYSTEM_PROMPT = (
    "You are a strict niche classifier for a YouTube Shorts channel about "
    "AI-centric tech news.\n\n"
    "Return \"on_niche\" only if the story's center of gravity is:\n"
    "- AI: a model or research release, or AI shipping inside a product "
    "(Apple Intelligence, Copilot, Gemini in Android, etc.), OR\n"
    "- A major flagship hardware/OS launch (new iPhone, a major iOS version, "
    "a flagship GPU).\n\n"
    "Return \"off_niche\" for culture, entertainment, adult-adjacent stories, "
    "lawsuits and industry drama, minor/incremental tech, startup funding "
    "rounds without a major product launch, and generic business news.\n\n"
    "When uncertain, prefer \"off_niche\".\n"
    'Return JSON only: {"verdict": "on_niche" or "off_niche", '
    '"reason": "<one short phrase>"}.'
)


@dataclass
class NicheVerdict:
    verdict: str
    reason: str
    infrastructure_failed: bool

    @property
    def is_on_niche(self) -> bool:
        return self.verdict == "on_niche"


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


def classify_niche(
    title: str,
    summary: str | None,
    *,
    model: str,
    host: Optional[str] = None,
) -> NicheVerdict:
    """One Ollama call, one retry. Never raises."""
    title = (title or "").strip()
    if not title:
        return NicheVerdict(
            verdict="off_niche",
            reason="empty title",
            infrastructure_failed=False,
        )

    host = (host or _ollama_host()).rstrip("/")
    summary_text = (summary or "").strip()
    user_prompt = (
        f"Headline: {title}\n"
        f"Summary: {summary_text or '(none)'}\n\n"
        "Return STRICT JSON."
    )

    last_error: Optional[Exception] = None
    for attempt in (1, 2):
        try:
            response = _post_chat(model, user_prompt, host)
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            logger.warning(f"niche_gate ollama HTTP error (attempt {attempt}): {exc}")
            if attempt == 2:
                return NicheVerdict(
                    verdict="off_niche",
                    reason=f"ollama unreachable: {exc}",
                    infrastructure_failed=True,
                )
            continue

        try:
            verdict, reason = _parse_response(response)
        except ValueError as exc:
            last_error = exc
            logger.warning(f"niche_gate ollama output invalid (attempt {attempt}): {exc}")
            user_prompt = (
                f"Headline: {title}\n"
                f"Summary: {summary_text or '(none)'}\n\n"
                f"IMPORTANT: previous response was invalid: {exc}. "
                'Return STRICT JSON: {"verdict": "on_niche" or "off_niche", '
                '"reason": "..."}.'
            )
            continue

        return NicheVerdict(
            verdict=verdict,
            reason=reason,
            infrastructure_failed=False,
        )

    return NicheVerdict(
        verdict="off_niche",
        reason=f"invalid output after retry: {last_error}",
        infrastructure_failed=True,
    )
