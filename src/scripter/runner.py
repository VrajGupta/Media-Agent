from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Callable

from src.scripter.shots import normalize_shots


def score_topics(topics: list[dict], scorer_fn: Callable) -> list[dict]:
    result = []
    for t in topics:
        raw = scorer_fn(t["title"], t.get("summary"))
        novelty = raw["novelty"]
        specificity = raw["specificity"]
        tension = raw["tension"]
        weighted = 0.4 * novelty + 0.3 * specificity + 0.3 * tension
        t = dict(t)
        t["topic_score_json"] = json.dumps({**raw, "weighted_score": weighted})
        t["weighted_score"] = weighted
        result.append(t)
    return result


def tag_categories(topics: list[dict], tagger_fn: Callable, allowed: list[str]) -> list[dict]:
    result = []
    for t in topics:
        cat = tagger_fn(t["title"], t.get("summary"))
        t = dict(t)
        t["category"] = cat if cat in allowed else allowed[0]
        result.append(t)
    return result


def select_topics(topics: list[dict], n: int = 4) -> list[dict]:
    seen_cats: set[str] = set()
    first_pass: list[dict] = []
    second_pass: list[dict] = []
    for t in sorted(topics, key=lambda x: x.get("weighted_score") or 0, reverse=True):
        cat = t.get("category")
        if cat not in seen_cats:
            seen_cats.add(cat)
            first_pass.append(t)
        else:
            second_pass.append(t)
    pool = first_pass + second_pass
    return pool[:n]


class ScriptRejectedError(Exception):
    pass


def validate_script(script: dict, cfg) -> tuple[bool, str | None]:
    sc = cfg.scripter
    narration = script.get("narration", "")
    word_count = len(narration.split())
    if word_count < sc.narration_word_count_min:
        return False, f"narration too short: {word_count} words (min {sc.narration_word_count_min})"
    if word_count > sc.narration_word_count_max:
        return False, f"narration too long: {word_count} words (max {sc.narration_word_count_max})"
    for token in sc.banned_tokens:
        if token.lower() in narration.lower():
            return False, f"banned token in narration: {token!r}"
    shots = script.get("shots", [])
    if len(shots) != 4:
        return False, f"expected 4 shots, got {len(shots)}"
    try:
        normalize_shots(shots)
    except ValueError as e:
        return False, str(e)
    return True, None


def generate_script(topic: dict, generator_fn: Callable, cfg) -> dict:
    sc = cfg.scripter
    last_err: Exception | None = None
    for _ in range(sc.retry_on_failure):
        try:
            result = generator_fn(topic["title"], topic.get("summary"))
        except Exception as e:
            last_err = e
            continue
        valid, reason = validate_script(result, cfg)
        if valid:
            return result
        last_err = ScriptRejectedError(reason)
    raise ScriptRejectedError(f"all retries exhausted for topic {topic['id']}") from last_err


def run_stage_b(
    cfg,
    repo,
    topics: list[dict],
    *,
    generator_fn: Callable | None = None,
) -> list[dict]:
    if not topics:
        return []
    sc = cfg.scripter
    results = []
    for t in topics:
        if generator_fn is None:
            results.append(t)
            continue
        try:
            script = generate_script(t, generator_fn, cfg)
            script = {**script, "shots": normalize_shots(script["shots"])}
        except Exception:
            continue
        script_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        repo.insert_script(
            script_id=script_id,
            topic_id=t["id"],
            title=script["title"],
            narration=script["narration"],
            shots_json=json.dumps(script["shots"]),
            style_suffix=sc.style_suffix,
            ollama_model=cfg.ollama_model,
            created_at=created_at,
            topic_score_json=t.get("topic_score_json"),
            category=t.get("category"),
        )
        repo.mark_topic_scripted(t["id"])
        results.append({**t, **script, "script_id": script_id})
    return results


def score_scripts(scripts: list[dict], scorer_fn: Callable) -> list[dict]:
    result = []
    for s in scripts:
        raw = scorer_fn(s["title"], s.get("narration"), s.get("shots"))
        hook = raw["hook_execution"]
        pacing = raw["pacing"]
        payoff = raw["payoff"]
        quality = 0.4 * hook + 0.3 * pacing + 0.3 * payoff
        s = dict(s)
        s["quality_score_json"] = json.dumps({**raw, "quality_score": quality})
        s["quality_score"] = quality
        result.append(s)
    return result


def select_scripts(scripts: list[dict], n: int = 2) -> list[dict]:
    return sorted(scripts, key=lambda x: x.get("quality_score") or 0, reverse=True)[:n]


def run_stage_c(
    cfg,
    repo,
    scripts: list[dict],
    *,
    scorer_fn: Callable | None = None,
) -> list[dict]:
    if not scripts:
        return []
    sc = cfg.scripter

    if scorer_fn is not None:
        scripts = score_scripts(scripts, scorer_fn)
        floor = sc.quality_floor
        passing = []
        for s in scripts:
            score = s.get("quality_score") or 0
            if score < floor:
                repo.update_script_status(
                    s["script_id"], "rejected",
                    rejection_reason=f"quality score {score:.2f} below floor {floor}",
                    quality_score=score,
                    quality_score_json=s.get("quality_score_json"),
                )
            else:
                repo.update_script_status(
                    s["script_id"], "pending",
                    quality_score=score,
                    quality_score_json=s.get("quality_score_json"),
                )
                passing.append(s)
        scripts = passing

    return select_scripts(scripts, sc.weekly_clip_target)


def run_stage_a(cfg, repo, *, scorer_fn: Callable | None = None, tagger_fn: Callable | None = None) -> list[dict]:
    sc = cfg.scripter
    rows = repo.unscripted_topics()
    topics = [dict(r) for r in rows]
    if not topics:
        return []

    if scorer_fn is not None:
        topics = score_topics(topics, scorer_fn)
        for t in topics:
            repo.update_topic_score(t["id"], t["topic_score_json"], t["weighted_score"])
        quality_floor = sc.quality_floor
        topics = [t for t in topics if (t.get("weighted_score") or 0) >= quality_floor]

    if tagger_fn is not None:
        topics = tag_categories(topics, tagger_fn, sc.categories)
        for t in topics:
            repo.update_topic_score(t["id"], t["topic_score_json"], t["weighted_score"], t.get("category"))

    return select_topics(topics, sc.candidate_pool_size)
