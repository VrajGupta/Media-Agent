"""Issue 32 — significance-based topic scoring."""

from __future__ import annotations

import json
from types import SimpleNamespace

from src.scripter.runner import score_topics
from src.topic_ingest.hn import HnItem


def _cfg(*, authority=None, hn_weight=2.0):
    return SimpleNamespace(
        scripter=SimpleNamespace(source_authority=authority or {}),
        topic_ingest=SimpleNamespace(hn=SimpleNamespace(corroboration_weight=hn_weight)),
    )


def test_score_topics_uses_significance_not_novelty_axes():
    topics = [{"id": 1, "title": "GPT-5 Released", "summary": None, "source_feed": "F"}]
    scored = score_topics(
        topics,
        lambda title, summary: {"significance": 8, "reason": "major launch"},
        _cfg(),
        hn_items=[],
    )
    assert abs(scored[0]["weighted_score"] - 8.0) < 0.001
    data = json.loads(scored[0]["topic_score_json"])
    assert "significance" in data
    assert "novelty" not in data


def test_score_topics_major_lab_launch_outranks_minor_item():
    def scorer(title, summary):
        if "Opus" in title:
            return {"significance": 9, "reason": "frontier model"}
        return {"significance": 4, "reason": "minor patch"}

    topics = [
        {"id": 1, "title": "Minor widget patch", "source_feed": "F"},
        {"id": 2, "title": "Claude Opus 4.7 released", "source_feed": "F"},
    ]
    scored = score_topics(topics, scorer, _cfg(), hn_items=[])
    by_id = {t["id"]: t["weighted_score"] for t in scored}
    assert by_id[2] > by_id[1]


def test_score_topics_primary_source_authority_boost():
    feed_primary = "https://openai.com/blog/rss.xml"
    topics = [
        {"id": 1, "title": "Same story", "source_feed": feed_primary},
        {"id": 2, "title": "Same story", "source_feed": "https://example.com/feed"},
    ]
    scored = score_topics(
        topics,
        lambda title, summary: {"significance": 8, "reason": "ok"},
        _cfg(authority={feed_primary: 1.5, "*": 1.0}),
        hn_items=[],
    )
    by_id = {t["id"]: t["weighted_score"] for t in scored}
    assert by_id[1] > by_id[2]


def test_score_topics_hn_corroborated_topic_boosted():
    topics = [
        {"id": 1, "title": "Claude Opus 4.7 released", "source_feed": "F"},
        {"id": 2, "title": "Unrelated minor update", "source_feed": "F"},
    ]
    hn_items = [HnItem(title="Anthropic releases Claude Opus 4.7", url="https://hn/1")]
    scored = score_topics(
        topics,
        lambda title, summary: {"significance": 7, "reason": "ok"},
        _cfg(),
        hn_items=hn_items,
    )
    by_id = {t["id"]: t["weighted_score"] for t in scored}
    assert by_id[1] > by_id[2]
