"""Licensed-only shot plan resolution for hybrid clips (ADR-0003)."""

from __future__ import annotations

from typing import Callable

LicensedProbe = Callable[[str, str | None], bool]


def _degrade_real_image_to_ai_video(shot: dict) -> dict:
    entity = shot["entity"]
    query = shot.get("search_query")
    prompt = f"cinematic tech b-roll transition, {entity}"
    if query:
        prompt = f"{prompt}, {query}"
    return {
        "kind": "ai_video",
        "prompt": prompt,
        "duration_s": shot.get("duration_s", 4),
    }


def resolve_shot_plan(
    shots: list[dict],
    *,
    licensed_probe: LicensedProbe,
) -> tuple[list[dict], int]:
    """Return (final shot list, billable ai_video count).

    Real-image shots that miss every licensed source degrade to ai_video
    before any Kling billing. ``licensed_probe`` must consult licensed sources
    only — never web search.
    """
    resolved: list[dict] = []
    for shot in shots:
        if shot.get("kind") == "real_image":
            entity = shot["entity"]
            query = shot.get("search_query")
            if licensed_probe(entity, query):
                resolved.append(shot)
            else:
                resolved.append(_degrade_real_image_to_ai_video(shot))
        else:
            resolved.append(shot)
    billable = sum(1 for s in resolved if s.get("kind") == "ai_video")
    return resolved, billable
