"""Pure shot normalization for Pivot.7 tagged schema."""

from __future__ import annotations

_DEFAULT_DURATION_S = 4


def _normalize_dict_shot(shot: dict) -> dict:
    kind = shot.get("kind")
    if kind == "real_image":
        entity = shot.get("entity")
        if not entity:
            raise ValueError("real_image shot requires non-empty 'entity'")
        return {
            "kind": "real_image",
            "entity": str(entity),
            "duration_s": shot.get("duration_s", _DEFAULT_DURATION_S),
            **({"search_query": shot["search_query"]} if "search_query" in shot else {}),
        }
    if kind == "ai_video":
        prompt = shot.get("prompt")
        if not prompt:
            raise ValueError("ai_video shot requires non-empty 'prompt'")
        return {
            "kind": "ai_video",
            "prompt": str(prompt),
            "duration_s": shot.get("duration_s", _DEFAULT_DURATION_S),
        }
    raise ValueError(f"unknown shot kind: {kind!r}")


def normalize_shots(raw_shots: list) -> list[dict]:
    normalized: list[dict] = []
    for shot in raw_shots:
        if isinstance(shot, str):
            normalized.append({
                "kind": "ai_video",
                "prompt": shot,
                "duration_s": _DEFAULT_DURATION_S,
            })
        elif isinstance(shot, dict):
            if "kind" not in shot and "prompt" in shot:
                shot = {**shot, "kind": "ai_video"}
            normalized.append(_normalize_dict_shot(shot))
        else:
            raise ValueError(f"invalid shot type: {type(shot).__name__}")
    return normalized
