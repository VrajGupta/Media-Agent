"""Real Ollama callables for Scripter Stages A, B, C.

Each factory returns a plain function matching the signature that the
corresponding runner stage expects. Pass these to run_stage_a / run_stage_b /
run_stage_c via the *_fn kwargs.
"""

from __future__ import annotations

import json
import re
from typing import Callable

import ollama

from src.scripter.shots import normalize_shots


def _chat_json(model: str, prompt: str) -> dict:
    resp = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        options={"temperature": 0.3},
    )
    raw = resp.message.content
    # Strip any accidental markdown fences
    raw = re.sub(r"```(?:json)?|```", "", raw).strip()
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Stage A: topic scorer
# ---------------------------------------------------------------------------

_TOPIC_SCORE_PROMPT = """\
Score this tech/AI news topic for a YouTube Shorts channel targeting AI-centric news.

Title: {title}
Summary: {summary}

Rate significance strictly 1-10 (integer):
- significance: How major is this launch or announcement? Consider model/research releases,
  AI shipping in products, and flagship hardware/OS launches as high significance.
  Culture, entertainment, lawsuits, minor patches, and startup funding rounds are low.

Also provide:
- reason: One sentence explaining the score

Score guidance:
1-3 = off-niche, minor/incremental, or low-impact
4-6 = moderate update with limited reach
7-8 = solid launch from a known player
9-10 = major frontier model, flagship device/OS, or industry-shifting release

Respond ONLY with valid JSON (use real scores, not placeholders):
{{"significance": <int 1-10>, "reason": "one sentence"}}
"""


def make_topic_scorer(model: str) -> Callable:
    def _fn(title: str, summary: str | None) -> dict:
        prompt = _TOPIC_SCORE_PROMPT.format(
            title=title, summary=summary or "N/A"
        )
        data = _chat_json(model, prompt)

        def _score(key: str) -> float:
            v = data.get(key, 5)
            try:
                return float(v)
            except (TypeError, ValueError):
                return 5.0

        return {
            "significance": _score("significance"),
            "reason": str(data.get("reason", "")),
        }
    return _fn


# ---------------------------------------------------------------------------
# Stage A: category tagger
# ---------------------------------------------------------------------------

_CATEGORIES = [
    "ai_models", "ai_features", "hardware", "software",
    "policy", "business", "science_research", "startup_funding",
]

_TAGGER_PROMPT = """\
Classify this tech/AI news topic into exactly one category.

Title: {title}
Summary: {summary}

Categories (pick ONE):
ai_models        - New model releases, benchmarks, capabilities
ai_features      - New features in existing AI products
hardware         - CPUs, GPUs, chips, physical devices
software         - Apps, platforms, operating systems
policy           - Regulation, legislation, AI safety rules
business         - Earnings, acquisitions, strategy, market moves
science_research - Academic papers, lab breakthroughs
startup_funding  - Startup news, VC rounds, new ventures

Respond ONLY with valid JSON:
{{"category": "<one of the categories above>"}}
"""


def make_topic_tagger(model: str) -> Callable:
    def _fn(title: str, summary: str | None) -> str:
        prompt = _TAGGER_PROMPT.format(title=title, summary=summary or "N/A")
        data = _chat_json(model, prompt)
        return str(data.get("category", "ai_models"))
    return _fn


# ---------------------------------------------------------------------------
# Stage B: script generator
# ---------------------------------------------------------------------------

_GENERATOR_PROMPT = """\
You are writing a voiceover script for a 30-second YouTube Shorts video about tech/AI news.

Story: {title}
Context: {summary}

Write the following JSON. Follow every rule exactly.

narration field rules:
1. Write FOUR complete sentences. No more, no less.
2. Sentence 1: hook — start with the most surprising number or fact.
3. Sentence 2: expand the context with another specific detail.
4. Sentence 3: explain why this matters.
5. Sentence 4: end with a tease ("Stay tuned." / "This is just the start." / similar).
6. Total must be 30-50 words. Count before writing.
7. No "I think". No "as an AI". No "<<placeholder>>".

shots field rules (exactly 4 tagged objects):
- Aim for ~2 real_image + ~2 ai_video, alternating so ai_video shots sit between real ones.
- real_image: the recognizable "money shot" — a real product, logo, or object viewers can identify.
  NEVER a living person. Use products, logos, hardware, or objects only.
  Schema: {{"kind": "real_image", "entity": "<concrete thing to source>", "search_query": "<optional refinement>", "duration_s": 4}}
- ai_video: abstract/atmospheric/transitional b-roll that connects the real shots.
  NEVER depict a person talking or yapping on screen.
  Schema: {{"kind": "ai_video", "prompt": "<10-20 word cinematic shot>", "duration_s": 4}}

JSON structure (output this exactly, no markdown fences):
{{
  "title": "5 to 8 word punchy title",
  "narration": "four sentences, 30-50 words total",
  "shots": [
    {{"kind": "real_image", "entity": "...", "duration_s": 4}},
    {{"kind": "ai_video", "prompt": "...", "duration_s": 4}},
    {{"kind": "real_image", "entity": "...", "duration_s": 4}},
    {{"kind": "ai_video", "prompt": "...", "duration_s": 4}}
  ],
  "style_notes": "brief visual aesthetic phrase"
}}
"""


def make_script_generator(model: str) -> Callable:
    def _fn(title: str, summary: str | None) -> dict:
        prompt = _GENERATOR_PROMPT.format(title=title, summary=summary or "N/A")
        data = _chat_json(model, prompt)
        shots = data.get("shots", [])
        # Normalise: if shots is a dict (model gave {0:..., 1:...}) convert to list
        if isinstance(shots, dict):
            shots = [shots[k] for k in sorted(shots)]
        return {
            "title": str(data["title"]),
            "narration": str(data["narration"]),
            "shots": normalize_shots(shots),
            "style_notes": str(data.get("style_notes", "")),
        }
    return _fn


# ---------------------------------------------------------------------------
# Stage C: script scorer
# ---------------------------------------------------------------------------

_SCRIPT_SCORE_PROMPT = """\
Score this YouTube Shorts script for a tech/AI news channel.

Title: {title}
Narration: {narration}
Shots:
{shots}

Rate each dimension strictly 1-10 (integers):
- hook_execution: Does the first line immediately grab attention? (1=weak, 10=irresistible)
- pacing: Is the narration tight and energetic throughout? (1=slow/padded, 10=perfect rhythm)
- payoff: Does it end on a satisfying tease that makes you want more? (1=flat, 10=must-watch)
- reason: One sentence explaining the scores

Score guidance:
1-3 = weak/flat  4-6 = average  7-8 = good  9-10 = exceptional

Respond ONLY with valid JSON (use real scores, not placeholders):
{{"hook_execution": <int 1-10>, "pacing": <int 1-10>, "payoff": <int 1-10>, "reason": "one sentence"}}
"""


def make_script_scorer(model: str) -> Callable:
    def _fn(title: str, narration: str, shots: list) -> dict:
        shots_text = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(shots or []))
        prompt = _SCRIPT_SCORE_PROMPT.format(
            title=title, narration=narration, shots=shots_text
        )
        data = _chat_json(model, prompt)
        def _score(key: str) -> float:
            v = data.get(key, 5)
            try:
                return float(v)
            except (TypeError, ValueError):
                return 5.0
        return {
            "hook_execution": _score("hook_execution"),
            "pacing": _score("pacing"),
            "payoff": _score("payoff"),
            "reason": str(data.get("reason", "")),
        }
    return _fn
