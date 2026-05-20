"""Ticket 05 — Scripter Stage C: script scoring + quality selection.

Tests verify observable behaviour through public interfaces.
Scorer callables are fully injected — no GPU or network required.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.state import Repository, connect, initialize_schema
from src.scripter.runner import score_scripts, select_scripts, run_stage_c


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path):
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _make_cfg(tmp_path, *, quality_floor=6.0, weekly_clip_target=2):
    weights = SimpleNamespace(hook_execution=0.4, pacing=0.3, payoff=0.3)
    s = SimpleNamespace(
        script_score_weights=weights,
        quality_floor=quality_floor,
        weekly_clip_target=weekly_clip_target,
    )
    return SimpleNamespace(
        scripter=s,
        paths=SimpleNamespace(logs_dir="logs"),
        abs_path=lambda rel: tmp_path / rel,
    )


def _good_scorer(hook=8, pacing=7, payoff=6):
    def _fn(title, narration, shots):
        return {"hook_execution": hook, "pacing": pacing, "payoff": payoff,
                "reason": "solid delivery"}
    return _fn


def _script(script_id, title="GPT-5 Drops", quality_score=None):
    s = {
        "script_id": script_id,
        "topic_id": 1,
        "title": title,
        "narration": "OpenAI just dropped GPT-5 and it rewrites every benchmark.",
        "shots": ["shot1", "shot2", "shot3", "shot4"],
        "topic_score_json": None,
        "category": "ai_models",
    }
    if quality_score is not None:
        s["quality_score"] = quality_score
        s["quality_score_json"] = json.dumps(
            {"hook_execution": 8, "pacing": 7, "payoff": 6,
             "reason": "ok", "quality_score": quality_score}
        )
    return s


def _insert_topic_and_script(repo, script_id, topic_id=1, title="GPT-5 Drops"):
    repo.conn.execute(
        "INSERT OR IGNORE INTO topics (id, url, title, source_feed, fetched_at) VALUES (?,?,?,?,?)",
        (topic_id, f"https://example.com/{topic_id}", title, "F", "2026-05-20T10:00:00Z"),
    )
    repo.insert_script(
        script_id=script_id,
        topic_id=topic_id,
        title=title,
        narration="OpenAI just dropped GPT-5 and it rewrites every benchmark.",
        shots_json=json.dumps(["shot1", "shot2", "shot3", "shot4"]),
        style_suffix="clean editorial",
        ollama_model="qwen2.5:3b-instruct",
        created_at="2026-05-20T10:00:00Z",
    )


# ---------------------------------------------------------------------------
# Tracer bullet: score_scripts enriches with quality_score + quality_score_json
# ---------------------------------------------------------------------------


def test_score_scripts_enriches_with_quality_score():
    scripts = [_script("s1")]
    scored = score_scripts(scripts, _good_scorer(hook=8, pacing=7, payoff=6))
    assert len(scored) == 1
    s = scored[0]
    assert "quality_score" in s
    assert "quality_score_json" in s
    assert abs(s["quality_score"] - (0.4*8 + 0.3*7 + 0.3*6)) < 0.001


# ---------------------------------------------------------------------------
# score_scripts: weighted formula + JSON keys
# ---------------------------------------------------------------------------


def test_score_scripts_weighted_formula():
    scripts = [_script("s1")]
    scored = score_scripts(scripts, _good_scorer(hook=10, pacing=5, payoff=5))
    expected = 0.4*10 + 0.3*5 + 0.3*5
    assert abs(scored[0]["quality_score"] - expected) < 0.001


def test_score_scripts_json_has_required_keys():
    scripts = [_script("s1")]
    scored = score_scripts(scripts, _good_scorer())
    data = json.loads(scored[0]["quality_score_json"])
    for key in ("hook_execution", "pacing", "payoff", "reason", "quality_score"):
        assert key in data, f"missing key: {key}"


# ---------------------------------------------------------------------------
# select_scripts: count cap + highest-score preference
# ---------------------------------------------------------------------------


def test_select_scripts_returns_at_most_n():
    scripts = [_script(f"s{i}", quality_score=float(i)) for i in range(6)]
    assert len(select_scripts(scripts, n=2)) == 2


def test_select_scripts_returns_highest_scoring():
    scripts = [
        _script("s1", quality_score=5.0),
        _script("s2", quality_score=9.0),
        _script("s3", quality_score=7.0),
    ]
    result = select_scripts(scripts, n=1)
    assert result[0]["script_id"] == "s2"


# ---------------------------------------------------------------------------
# run_stage_c: orchestrator behaviours
# ---------------------------------------------------------------------------


def test_run_stage_c_returns_empty_for_empty_input(tmp_path, repo):
    cfg = _make_cfg(tmp_path)
    assert run_stage_c(cfg, repo, []) == []


def test_run_stage_c_scores_all_scripts(tmp_path, repo):
    cfg = _make_cfg(tmp_path)
    scripts = [_script("s1"), _script("s2")]
    for s in scripts:
        _insert_topic_and_script(repo, s["script_id"], topic_id=int(s["script_id"][1:]),
                                  title=s["title"])
    result = run_stage_c(cfg, repo, scripts, scorer_fn=_good_scorer(hook=8, pacing=7, payoff=7))
    for s in result:
        assert "quality_score" in s


def test_run_stage_c_persists_quality_scores(tmp_path, repo):
    cfg = _make_cfg(tmp_path)
    _insert_topic_and_script(repo, "s1")
    scripts = [_script("s1")]
    run_stage_c(cfg, repo, scripts, scorer_fn=_good_scorer(hook=8, pacing=7, payoff=6))
    row = repo.conn.execute("SELECT quality_score FROM scripts WHERE script_id='s1'").fetchone()
    assert row is not None
    assert abs(row["quality_score"] - (0.4*8 + 0.3*7 + 0.3*6)) < 0.001


def test_run_stage_c_rejects_below_quality_floor(tmp_path, repo):
    cfg = _make_cfg(tmp_path, quality_floor=8.0)
    # hook=5, pacing=5, payoff=5 → quality = 5.0, below floor 8.0
    _insert_topic_and_script(repo, "s1")
    scripts = [_script("s1")]
    result = run_stage_c(cfg, repo, scripts, scorer_fn=_good_scorer(hook=5, pacing=5, payoff=5))
    assert result == []
    row = repo.conn.execute("SELECT status FROM scripts WHERE script_id='s1'").fetchone()
    assert row["status"] == "rejected"


def test_run_stage_c_returns_at_most_weekly_clip_target(tmp_path, repo):
    cfg = _make_cfg(tmp_path, weekly_clip_target=2)
    for i in range(5):
        _insert_topic_and_script(repo, f"s{i}", topic_id=i+1, title=f"Topic {i}")
    scripts = [_script(f"s{i}", title=f"Topic {i}") for i in range(5)]
    result = run_stage_c(cfg, repo, scripts, scorer_fn=_good_scorer(hook=8, pacing=7, payoff=7))
    assert len(result) <= 2


def test_run_stage_c_no_scorer_returns_all_unscored(tmp_path, repo):
    cfg = _make_cfg(tmp_path)
    _insert_topic_and_script(repo, "s1")
    scripts = [_script("s1")]
    result = run_stage_c(cfg, repo, scripts)
    assert len(result) == 1
