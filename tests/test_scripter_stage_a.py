"""Ticket 03 — Scripter Stage A: topic scoring + categorization + diversity selection.

Tests verify observable behaviour through public interfaces.
Ollama callables are fully injected — no GPU or network required.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.state import Repository, connect, initialize_schema
from src.scripter.runner import score_topics, tag_categories, select_topics, run_stage_a


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_CATEGORIES = ["ai_models", "ai_features", "hardware", "software",
               "policy", "business", "science_research", "startup_funding"]


@pytest.fixture
def repo(tmp_path):
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _make_cfg(tmp_path, *, categories=None, quality_floor=6.0, candidate_pool_size=4):
    cats = categories if categories is not None else _CATEGORIES
    s = SimpleNamespace(
        categories=cats,
        candidate_pool_size=candidate_pool_size,
        quality_floor=quality_floor,
        source_authority={"*": 1.0},
    )
    return SimpleNamespace(
        scripter=s,
        topic_ingest=SimpleNamespace(hn=SimpleNamespace(enabled=False)),
        paths=SimpleNamespace(logs_dir="logs"),
        abs_path=lambda rel: tmp_path / rel,
    )


def _topic(id_, title, category=None, weighted_score=None):
    """Build a dict that mimics a scored/categorized topic."""
    t = {"id": id_, "title": title, "summary": None}
    if category is not None:
        t["category"] = category
    if weighted_score is not None:
        t["weighted_score"] = weighted_score
        t["topic_score_json"] = json.dumps({"significance": 7, "reason": "ok",
                                            "weighted_score": weighted_score, "hn_boost": 0})
    return t


def _good_scorer(significance=8):
    def _fn(title, summary):
        return {"significance": significance, "reason": "solid story"}
    return _fn


def _insert_topics(repo, titles_categories):
    """Insert topics into DB and return their ids."""
    ids = []
    for i, (title, cat) in enumerate(titles_categories):
        tid = repo.insert_topic(
            url=f"https://example.com/{i}", title=title, source_feed="F",
            fetched_at="2026-05-19T10:00:00Z",
        )
        ids.append(tid)
    return ids


# ---------------------------------------------------------------------------
# Tracer bullet: score_topics enriches with weighted_score + topic_score_json
# ---------------------------------------------------------------------------


def test_score_topics_enriches_with_weighted_score():
    topics = [{"id": 1, "title": "GPT-5 Released", "summary": None, "source_feed": "F"}]
    cfg = SimpleNamespace(
        scripter=SimpleNamespace(source_authority={"*": 1.0}),
        topic_ingest=SimpleNamespace(hn=SimpleNamespace(corroboration_weight=2.0)),
    )
    scored = score_topics(topics, _good_scorer(significance=8), cfg, hn_items=[])
    assert len(scored) == 1
    t = scored[0]
    assert "topic_score_json" in t
    assert "weighted_score" in t
    assert abs(t["weighted_score"] - 8.0) < 0.001


# ---------------------------------------------------------------------------
# score_topics: topic_score_json is valid JSON with expected keys
# ---------------------------------------------------------------------------


def test_score_topics_json_has_required_keys():
    topics = [{"id": 1, "title": "Nvidia H200 Ships", "summary": None, "source_feed": "F"}]
    cfg = SimpleNamespace(
        scripter=SimpleNamespace(source_authority={"*": 1.0}),
        topic_ingest=SimpleNamespace(hn=SimpleNamespace(corroboration_weight=2.0)),
    )
    scored = score_topics(topics, _good_scorer(), cfg, hn_items=[])
    data = json.loads(scored[0]["topic_score_json"])
    for key in ("significance", "reason", "weighted_score", "hn_boost"):
        assert key in data, f"missing key: {key}"


# ---------------------------------------------------------------------------
# tag_categories: happy path + fallback on unknown value
# ---------------------------------------------------------------------------


def test_tag_categories_assigns_returned_category():
    topics = [{"id": 1, "title": "GPT-5 Released", "summary": None}]
    result = tag_categories(topics, lambda title, summary: "ai_models", _CATEGORIES)
    assert result[0]["category"] == "ai_models"


def test_tag_categories_falls_back_when_unknown():
    topics = [{"id": 1, "title": "Weird Topic", "summary": None}]
    result = tag_categories(topics, lambda title, summary: "unknown_junk", _CATEGORIES)
    assert result[0]["category"] == _CATEGORIES[0]


# ---------------------------------------------------------------------------
# select_topics: count cap + highest-score preference + diversity
# ---------------------------------------------------------------------------


def test_select_topics_returns_at_most_n():
    topics = [_topic(i, f"T{i}", category="ai_models", weighted_score=float(i))
              for i in range(10)]
    assert len(select_topics(topics, n=4)) == 4


def test_select_topics_prefers_highest_scores():
    topics = [
        _topic(1, "Low", category="ai_models", weighted_score=5.0),
        _topic(2, "High", category="ai_models", weighted_score=9.0),
        _topic(3, "Mid", category="ai_models", weighted_score=7.0),
    ]
    result = select_topics(topics, n=1)
    assert result[0]["id"] == 2


def test_select_topics_diversity_prefers_different_categories():
    topics = [
        _topic(1, "A1", category="ai_models", weighted_score=9.0),
        _topic(2, "A2", category="ai_models", weighted_score=8.5),
        _topic(3, "H1", category="hardware", weighted_score=8.0),
        _topic(4, "S1", category="software", weighted_score=7.5),
    ]
    result = select_topics(topics, n=3)
    cats = [t["category"] for t in result]
    assert len(set(cats)) == 3, f"expected 3 unique categories, got {cats}"


# ---------------------------------------------------------------------------
# run_stage_a: orchestrator behaviours
# ---------------------------------------------------------------------------


def test_run_stage_a_returns_empty_when_no_unscripted(tmp_path, repo):
    cfg = _make_cfg(tmp_path)
    result = run_stage_a(cfg, repo, scorer_fn=_good_scorer(), tagger_fn=lambda t, s: "ai_models")
    assert result == []


def test_run_stage_a_scores_all_unscripted_topics(tmp_path, repo):
    cfg = _make_cfg(tmp_path)
    _insert_topics(repo, [("GPT-5 Lands", "ai_models"), ("TSMC 2nm", "hardware")])
    result = run_stage_a(cfg, repo, scorer_fn=_good_scorer(significance=8),
                         tagger_fn=lambda t, s: "ai_models")
    assert len(result) == 2
    for t in result:
        assert "weighted_score" in t


def test_run_stage_a_persists_scores(tmp_path, repo):
    cfg = _make_cfg(tmp_path)
    ids = _insert_topics(repo, [("OpenAI o3 launch", "ai_models")])
    run_stage_a(cfg, repo, scorer_fn=_good_scorer(significance=8),
                tagger_fn=lambda t, s: "ai_models")
    rows = repo.unscripted_topics()
    scored = [r for r in rows if r["weighted_score"] is not None]
    assert len(scored) == 1
    assert abs(scored[0]["weighted_score"] - 8.0) < 0.001


def test_run_stage_a_filters_below_quality_floor(tmp_path, repo):
    cfg = _make_cfg(tmp_path, quality_floor=8.0)
    _insert_topics(repo, [("Topic Low", None), ("Topic High", None)])
    calls = []

    def scorer(title, summary):
        score = 9 if "High" in title else 5
        calls.append(title)
        return {"significance": score, "reason": "x"}

    result = run_stage_a(cfg, repo, scorer_fn=scorer, tagger_fn=lambda t, s: "ai_models")
    titles = [t["title"] for t in result]
    assert "Topic High" in titles
    assert "Topic Low" not in titles


def test_run_stage_a_returns_at_most_candidate_pool_size(tmp_path, repo):
    cfg = _make_cfg(tmp_path, candidate_pool_size=2)
    _insert_topics(repo, [(f"Topic {i}", None) for i in range(6)])
    result = run_stage_a(cfg, repo, scorer_fn=_good_scorer(significance=8),
                         tagger_fn=lambda t, s: _CATEGORIES[t.count(" ") % len(_CATEGORIES)])
    assert len(result) <= 2


def test_run_stage_a_no_scorer_no_tagger_returns_unscripted(tmp_path, repo):
    cfg = _make_cfg(tmp_path)
    _insert_topics(repo, [("Topic A", None), ("Topic B", None)])
    result = run_stage_a(cfg, repo)
    assert len(result) == 2
