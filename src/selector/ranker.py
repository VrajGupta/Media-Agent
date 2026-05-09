"""Ollama-based clip ranker (Phase 3).

One HTTP call per video. The user message contains all candidate windows
labeled by `candidate_id` ("c0", "c1", ...). The model returns top-K IDs;
selector maps IDs back to canonical timestamps locally — never trusts the
model to invent start/end values.

Failure modes (all handled by leaving the video at status='transcribed' and
appending a rolled-up alert at run end):
  - Ollama unreachable / network error
  - Malformed JSON
  - Returned candidate_id missing / unknown / duplicated
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Optional

import requests
from loguru import logger

from src.selector.windows import Window

_PLACEHOLDER_RE = re.compile(r"<<.*?>>")

DEFAULT_HOST = "http://localhost:11434"
TIMEOUT_SECONDS = 60.0
KEEP_ALIVE = "10m"

SYSTEM_PROMPT = (
    "You are a clip-selection assistant for a YouTube Shorts repost channel. "
    "Given candidate windows of a long-form video transcript, pick the BEST hooks "
    "for short-form repost. Score each window using this rubric:\n"
    "  - hook strength: does the first sentence make a viewer stop scrolling?\n"
    "  - payoff: does the window deliver on its premise within 30-60s?\n"
    "  - self-contained: is it understandable without prior context?\n"
    "  - controversy or curiosity: is there a question, claim, or tension?\n"
    "  - no slow intro: avoid windows that start with throat-clearing.\n"
    "Return JSON only. Schema: "
    '{"clips": [{"candidate_id": "<id>", "hook": "<one-line attention grab>", '
    '"suggested_title": "<<=70 char title>", "score": <0-10 float>}, ...]}. '
    "Pick the top N as instructed. Use ONLY candidate_ids that appear in the "
    "input. Never invent timestamps. "
    "Do NOT include angle brackets, square brackets, or example placeholders "
    "like '<<...>>' in any field — write a real title."
)


@dataclass
class RankedClip:
    candidate_id: str
    hook: str
    suggested_title: str
    score: float


class RankerError(Exception):
    """Persistent ranker failure (network or invalid output after retry)."""


def _ollama_host() -> str:
    return os.environ.get("OLLAMA_HOST", DEFAULT_HOST).rstrip("/")


def _build_user_prompt(windows: list[Window], top_n: int) -> str:
    lines = [
        f"Pick the top {top_n} candidates from this video.",
        "",
        "Candidates:",
    ]
    for w in windows:
        marker = " [HEATMAP_PEAK]" if w.heatmap_peak else ""
        lines.append(f"- {w.candidate_id}{marker} ({w.duration_s:.1f}s): {w.text}")
    lines.append("")
    lines.append("Return ONLY valid JSON in the schema specified.")
    return "\n".join(lines)


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


def _extract_clips_from_response(response: dict) -> list[dict]:
    """Pull the assistant message content and parse it as JSON. Raises ValueError
    on malformed output."""
    try:
        content = response["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"missing message.content in response: {exc}") from exc
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"content is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"top-level JSON is not an object: {type(parsed).__name__}")
    clips = parsed.get("clips")
    if not isinstance(clips, list):
        raise ValueError("response missing 'clips' array")
    return clips


def _validate_clips(
    raw_clips: list[dict],
    valid_ids: set[str],
    top_n: int,
) -> list[RankedClip]:
    """Each clip must have a known, unique candidate_id and required fields."""
    if not raw_clips:
        raise ValueError("empty 'clips' array")
    seen: set[str] = set()
    out: list[RankedClip] = []
    for c in raw_clips[:top_n]:
        if not isinstance(c, dict):
            raise ValueError(f"clip entry is not an object: {type(c).__name__}")
        cid = c.get("candidate_id")
        if cid not in valid_ids:
            raise ValueError(f"unknown candidate_id: {cid!r}")
        if cid in seen:
            raise ValueError(f"duplicate candidate_id: {cid!r}")
        seen.add(cid)
        hook = c.get("hook")
        title = c.get("suggested_title")
        if not isinstance(hook, str) or not hook.strip():
            raise ValueError(f"missing/empty hook for {cid}")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"missing/empty suggested_title for {cid}")
        if _PLACEHOLDER_RE.search(title):
            # Live regression (Pivot.3 verification on cApYKxhFcm0):
            # Ollama can echo the rubric example placeholder "<<=70 char title>>"
            # as a literal title. Reject so the runner retries with a stricter
            # prompt; persistent failures leave the video at 'transcribed'.
            raise ValueError(
                f"placeholder leaked into suggested_title for {cid}: {title!r}"
            )
        try:
            score = float(c.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        out.append(RankedClip(
            candidate_id=cid,
            hook=hook.strip(),
            suggested_title=title.strip(),
            score=score,
        ))
    if len(out) < min(top_n, len(valid_ids)):
        raise ValueError(f"only {len(out)} valid clips returned, expected {top_n}")
    return out


def rank_windows(
    windows: list[Window],
    *,
    model: str,
    top_n: int,
    host: Optional[str] = None,
) -> list[RankedClip]:
    """One Ollama call (with one retry on validation failure). Raises RankerError
    on persistent failure; caller leaves video at 'transcribed' and alerts."""
    if not windows:
        raise RankerError("no candidate windows to rank")

    host = (host or _ollama_host()).rstrip("/")
    valid_ids = {w.candidate_id for w in windows}
    user_prompt = _build_user_prompt(windows, top_n)

    last_error: Optional[Exception] = None
    for attempt in (1, 2):
        try:
            response = _post_chat(model, user_prompt, host)
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            logger.warning(f"ollama HTTP error (attempt {attempt}): {exc}")
            # Network/HTTP error — retry once.
            if attempt == 2:
                raise RankerError(f"ollama unreachable: {exc}") from exc
            continue

        try:
            raw_clips = _extract_clips_from_response(response)
            return _validate_clips(raw_clips, valid_ids, top_n)
        except ValueError as exc:
            last_error = exc
            logger.warning(f"ollama output invalid (attempt {attempt}): {exc}")
            # Tighten user prompt for the retry.
            user_prompt = (
                _build_user_prompt(windows, top_n)
                + "\n\nIMPORTANT: previous response was invalid: "
                + str(exc)
                + ". Use ONLY the candidate_ids listed above. Return STRICT JSON."
            )

    raise RankerError(f"ollama returned invalid output after retry: {last_error}")
