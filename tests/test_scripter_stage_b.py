"""Ticket 04 — Scripter Stage B: script generation, validation, persistence.

Tests verify observable behaviour through public interfaces.
Ollama callables are fully injected — no GPU or network required.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.state import Repository, connect, initialize_schema
from src.scripter.runner import validate_script, generate_script, run_stage_b


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_SHOTS = ["A glowing chip on a dark desk", "Engineer stares at holographic display",
          "Stock ticker spikes in red", "Phone screen glows with headline text"]


@pytest.fixture
def repo(tmp_path):
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _make_cfg(tmp_path, *, wc_min=30, wc_max=50, retries=3):
    s = SimpleNamespace(
        narration_word_count_min=wc_min,
        narration_word_count_max=wc_max,
        banned_tokens=["<<placeholder>>", "I think", "as an AI"],
        retry_on_failure=retries,
        style_suffix="clean editorial product photography",
        candidate_pool_size=4,
    )
    return SimpleNamespace(
        scripter=s,
        ollama_model="qwen2.5:3b-instruct",
        paths=SimpleNamespace(logs_dir="logs"),
        abs_path=lambda rel: tmp_path / rel,
    )


def _good_script(narration=None):
    """Build a valid script dict."""
    if narration is None:
        narration = ("OpenAI just dropped GPT-5 and it demolishes every reasoning benchmark "
                     "by a staggering margin. Two hundred billion parameters trained on "
                     "synthetic chain-of-thought data. Performance on math and code simply "
                     "breaks the leaderboard. This changes everything we thought about AI.")
    return {
        "title": "GPT-5 Drops and Rewrites the Rules",
        "narration": narration,
        "shots": list(_SHOTS),
        "style_notes": "dark moody tech aesthetic",
    }


def _word_count(text: str) -> int:
    return len(text.split())


def _make_generator(script: dict | None = None, fail_first: int = 0):
    """Returns a generator_fn. If fail_first > 0, raises ValueError that many times first."""
    calls = [0]

    def _fn(title, summary):
        calls[0] += 1
        if calls[0] <= fail_first:
            raise ValueError("Ollama returned invalid JSON")
        return script if script is not None else _good_script()

    return _fn


# ---------------------------------------------------------------------------
# Tracer bullet: validate_script accepts a good script
# ---------------------------------------------------------------------------


def test_validate_script_accepts_good_script(tmp_path):
    cfg = _make_cfg(tmp_path)
    valid, reason = validate_script(_good_script(), cfg)
    assert valid is True
    assert reason is None


# ---------------------------------------------------------------------------
# validate_script: rejection cases
# ---------------------------------------------------------------------------


def test_validate_script_rejects_narration_too_short(tmp_path):
    cfg = _make_cfg(tmp_path, wc_min=30)
    short_script = _good_script(narration="Too short narration here.")
    valid, reason = validate_script(short_script, cfg)
    assert valid is False
    assert reason is not None


def test_validate_script_rejects_narration_too_long(tmp_path):
    cfg = _make_cfg(tmp_path, wc_max=10)
    long_script = _good_script()
    valid, reason = validate_script(long_script, cfg)
    assert valid is False
    assert reason is not None


def test_validate_script_rejects_banned_token_in_narration(tmp_path):
    cfg = _make_cfg(tmp_path)
    bad = _good_script(narration=(
        "I think this new chip from TSMC is going to reshape the industry. "
        "Two nanometer nodes arrive this quarter with massive efficiency gains. "
        "The race for AI supremacy has a new front runner now."
    ))
    valid, reason = validate_script(bad, cfg)
    assert valid is False
    assert "banned" in reason.lower()


def test_validate_script_rejects_wrong_shots_count(tmp_path):
    cfg = _make_cfg(tmp_path)
    script = _good_script()
    script["shots"] = ["Only one shot"]
    valid, reason = validate_script(script, cfg)
    assert valid is False
    assert reason is not None


# ---------------------------------------------------------------------------
# generate_script: happy path + retry logic
# ---------------------------------------------------------------------------


def test_generate_script_returns_valid_script(tmp_path):
    cfg = _make_cfg(tmp_path)
    topic = {"id": 1, "title": "TSMC 2nm Ready", "summary": None}
    result = generate_script(topic, _make_generator(), cfg)
    assert result["title"] is not None
    assert "narration" in result
    assert len(result["shots"]) == 4


def test_generate_script_retries_on_validation_failure(tmp_path):
    cfg = _make_cfg(tmp_path, retries=3)
    topic = {"id": 1, "title": "Test", "summary": None}

    call_count = [0]
    bad_script = _good_script(narration="Too short.")  # will fail validation

    def flaky(title, summary):
        call_count[0] += 1
        if call_count[0] < 3:
            return bad_script
        return _good_script()

    result = generate_script(topic, flaky, cfg)
    assert call_count[0] == 3
    assert result["narration"] != "Too short."


def test_generate_script_raises_after_all_retries_exhausted(tmp_path):
    cfg = _make_cfg(tmp_path, retries=2)
    topic = {"id": 1, "title": "Test", "summary": None}
    always_bad = _make_generator(script=_good_script(narration="Too short."))
    with pytest.raises(Exception):
        generate_script(topic, always_bad, cfg)


# ---------------------------------------------------------------------------
# run_stage_b: orchestrator behaviours
# ---------------------------------------------------------------------------


def test_run_stage_b_empty_topics_returns_empty(tmp_path, repo):
    cfg = _make_cfg(tmp_path)
    result = run_stage_b(cfg, repo, [], generator_fn=_make_generator())
    assert result == []


def test_run_stage_b_generates_script_for_each_topic(tmp_path, repo):
    cfg = _make_cfg(tmp_path)
    topics = [
        {"id": 1, "title": "GPT-5 Drops", "summary": None, "topic_score_json": None, "category": None},
        {"id": 2, "title": "TSMC 2nm Ships", "summary": None, "topic_score_json": None, "category": None},
    ]
    # Insert topics so FK holds
    for t in topics:
        repo.conn.execute(
            "INSERT INTO topics (id, url, title, source_feed, fetched_at) VALUES (?,?,?,?,?)",
            (t["id"], f"https://example.com/{t['id']}", t["title"], "F", "2026-05-20T10:00:00Z"),
        )
    result = run_stage_b(cfg, repo, topics, generator_fn=_make_generator())
    assert len(result) == 2


def test_run_stage_b_persists_scripts_to_db(tmp_path, repo):
    cfg = _make_cfg(tmp_path)
    topic = {"id": 1, "title": "Nvidia H200 Ships", "summary": None, "topic_score_json": None, "category": None}
    repo.conn.execute(
        "INSERT INTO topics (id, url, title, source_feed, fetched_at) VALUES (?,?,?,?,?)",
        (1, "https://example.com/1", topic["title"], "F", "2026-05-20T10:00:00Z"),
    )
    run_stage_b(cfg, repo, [topic], generator_fn=_make_generator())
    rows = repo.conn.execute("SELECT * FROM scripts WHERE topic_id=1").fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["title"] is not None
    assert row["narration"] is not None
    assert row["status"] == "pending"


def test_run_stage_b_marks_topic_scripted(tmp_path, repo):
    cfg = _make_cfg(tmp_path)
    topic = {"id": 1, "title": "OpenAI o3 Lands", "summary": None, "topic_score_json": None, "category": None}
    repo.conn.execute(
        "INSERT INTO topics (id, url, title, source_feed, fetched_at) VALUES (?,?,?,?,?)",
        (1, "https://example.com/1", topic["title"], "F", "2026-05-20T10:00:00Z"),
    )
    run_stage_b(cfg, repo, [topic], generator_fn=_make_generator())
    row = repo.conn.execute("SELECT status FROM topics WHERE id=1").fetchone()
    assert row["status"] == "scripted"


def test_run_stage_b_skips_topic_when_all_retries_fail(tmp_path, repo):
    cfg = _make_cfg(tmp_path, retries=1)
    topics = [
        {"id": 1, "title": "Good Topic", "summary": None, "topic_score_json": None, "category": None},
        {"id": 2, "title": "Bad Topic", "summary": None, "topic_score_json": None, "category": None},
    ]
    for t in topics:
        repo.conn.execute(
            "INSERT INTO topics (id, url, title, source_feed, fetched_at) VALUES (?,?,?,?,?)",
            (t["id"], f"https://example.com/{t['id']}", t["title"], "F", "2026-05-20T10:00:00Z"),
        )

    def selective_gen(title, summary):
        if "Bad" in title:
            return _good_script(narration="Short.")  # always fails validation
        return _good_script()

    result = run_stage_b(cfg, repo, topics, generator_fn=selective_gen)
    assert len(result) == 1
    rows = repo.conn.execute("SELECT COUNT(*) FROM scripts").fetchone()[0]
    assert rows == 1
    # The one persisted script belongs to the good topic (id=1)
    assert repo.conn.execute("SELECT COUNT(*) FROM scripts WHERE topic_id=1").fetchone()[0] == 1
    assert repo.conn.execute("SELECT COUNT(*) FROM scripts WHERE topic_id=2").fetchone()[0] == 0
