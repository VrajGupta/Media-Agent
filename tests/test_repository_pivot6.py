"""Pivot.6 schema migration + DAL helpers (Ticket 01).

Tests verify observable behaviour through public interfaces:
- schema.sql fresh-DB produces correct Pivot.6 tables + columns
- migrate_pivot_6_3 applies Pivot.6 changes to a legacy DB idempotently
- repository.py DAL helpers insert, query, and transition status correctly
"""

from __future__ import annotations

import sqlite3

import pytest

from src.state import Repository, connect, initialize_schema


# ---------------------------------------------------------------------------
# Legacy schema helper — simulates a pre-Pivot.6 DB for migration tests
# ---------------------------------------------------------------------------

_LEGACY_DDL = """
CREATE TABLE videos (
    video_id TEXT PRIMARY KEY, title TEXT NOT NULL, channel TEXT NOT NULL,
    duration_seconds INTEGER NOT NULL, views INTEGER NOT NULL,
    likes INTEGER NOT NULL DEFAULT 0, comments INTEGER NOT NULL DEFAULT 0,
    published_at TEXT NOT NULL, keyword TEXT NOT NULL,
    virality_score REAL NOT NULL, status TEXT NOT NULL,
    rejection_reason TEXT, discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE clips (
    clip_id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    start_s REAL NOT NULL, end_s REAL NOT NULL,
    hook TEXT NOT NULL, suggested_title TEXT NOT NULL,
    selection_method TEXT NOT NULL, status TEXT NOT NULL,
    rejection_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE quota_usage (
    date TEXT NOT NULL, endpoint TEXT NOT NULL,
    units INTEGER NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _legacy_conn(tmp_path) -> sqlite3.Connection:
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_LEGACY_DDL)
    return conn


@pytest.fixture
def repo(tmp_path):
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


# ---------------------------------------------------------------------------
# Migration: apply Pivot.6 changes to a legacy DB
# ---------------------------------------------------------------------------


def test_migration_adds_topics_table_to_legacy_db(tmp_path):
    from scripts.migrate_pivot_6_3 import migrate
    conn = _legacy_conn(tmp_path)
    migrate(conn)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"topics", "seen_topics", "scripts", "generation_jobs"} <= tables


def test_migration_adds_content_kind_column(tmp_path):
    from scripts.migrate_pivot_6_3 import migrate
    conn = _legacy_conn(tmp_path)
    migrate(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(clips)").fetchall()}
    assert "content_kind" in cols


def test_migration_adds_provider_column_to_quota_usage(tmp_path):
    from scripts.migrate_pivot_6_3 import migrate
    conn = _legacy_conn(tmp_path)
    migrate(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(quota_usage)").fetchall()}
    assert "provider" in cols


def test_migration_makes_clips_video_id_nullable(tmp_path):
    from scripts.migrate_pivot_6_3 import migrate
    conn = _legacy_conn(tmp_path)
    migrate(conn)
    info = {r["name"]: r for r in conn.execute("PRAGMA table_info(clips)").fetchall()}
    assert info["video_id"]["notnull"] == 0


def test_migration_dry_run_does_not_apply_changes(tmp_path):
    from scripts.migrate_pivot_6_3 import migrate
    conn = _legacy_conn(tmp_path)
    ops = migrate(conn, dry_run=True)
    assert ops  # has planned ops
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "topics" not in tables  # nothing was actually applied


def test_migration_is_idempotent(tmp_path):
    from scripts.migrate_pivot_6_3 import migrate
    conn = _legacy_conn(tmp_path)
    migrate(conn)
    migrate(conn)  # second run must not raise or drift schema
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(clips)").fetchall()}
    assert "content_kind" in cols


def test_migration_preserves_existing_rows(tmp_path):
    from scripts.migrate_pivot_6_3 import migrate
    conn = _legacy_conn(tmp_path)
    conn.execute(
        "INSERT INTO videos (video_id, title, channel, duration_seconds, views, "
        "published_at, keyword, virality_score, status) "
        "VALUES ('v1', 'T', 'C', 60, 0, '2026-01-01', 'k', 1.0, 'discovered')"
    )
    conn.execute(
        "INSERT INTO clips (clip_id, video_id, start_s, end_s, hook, "
        "suggested_title, selection_method, status) "
        "VALUES ('c1', 'v1', 0.0, 5.0, 'H', 'T', 'heatmap_aided', 'quality_pass')"
    )
    conn.commit()
    migrate(conn)
    row = conn.execute("SELECT * FROM clips WHERE clip_id='c1'").fetchone()
    assert row is not None
    assert row["video_id"] == "v1"
    assert row["content_kind"] == "sourced"


def test_fk_enforcement_rejects_invalid_topic_id_on_scripts(repo):
    with pytest.raises(sqlite3.IntegrityError):
        repo.conn.execute(
            "INSERT INTO scripts (script_id, topic_id, title, narration, shots_json, "
            "style_suffix, ollama_model, created_at) "
            "VALUES ('s1', 9999, 'T', 'N', '[]', 'suffix', 'qwen', '2026-05-19T00:00:00Z')"
        )


# ---------------------------------------------------------------------------
# Tracer bullet: fresh DB has all Pivot.6 tables
# ---------------------------------------------------------------------------


def test_fresh_db_has_topics_table(repo):
    cols = {r["name"] for r in repo.conn.execute("PRAGMA table_info(topics)").fetchall()}
    assert {"id", "url", "title", "summary", "source_feed", "fetched_at", "published_at", "status"} <= cols


def test_fresh_db_has_seen_topics_table(repo):
    cols = {r["name"] for r in repo.conn.execute("PRAGMA table_info(seen_topics)").fetchall()}
    assert {"url_hash", "title_normalized", "first_seen_at"} <= cols


def test_fresh_db_has_scripts_table(repo):
    cols = {r["name"] for r in repo.conn.execute("PRAGMA table_info(scripts)").fetchall()}
    assert {"script_id", "topic_id", "title", "narration", "shots_json",
            "style_suffix", "ollama_model", "quality_score", "status"} <= cols


def test_fresh_db_has_generation_jobs_table(repo):
    cols = {r["name"] for r in repo.conn.execute("PRAGMA table_info(generation_jobs)").fetchall()}
    assert {"job_id", "script_id", "shot_index", "provider", "prompt",
            "duration_s", "status", "cost_cents"} <= cols


def test_clips_video_id_is_nullable(repo):
    repo.conn.execute(
        "INSERT INTO clips (clip_id, start_s, end_s, hook, suggested_title, selection_method, status) "
        "VALUES ('ai-clip-1', 0.0, 16.0, 'Hook', 'Title', 'ai_generated', 'selected')"
    )
    row = repo.conn.execute("SELECT video_id FROM clips WHERE clip_id='ai-clip-1'").fetchone()
    assert row is not None
    assert row["video_id"] is None


def test_clips_content_kind_defaults_to_sourced(repo):
    repo.conn.execute(
        "INSERT INTO clips (clip_id, start_s, end_s, hook, suggested_title, selection_method, status) "
        "VALUES ('ck-clip', 0.0, 5.0, 'H', 'T', 'ai_generated', 'selected')"
    )
    row = repo.conn.execute("SELECT content_kind FROM clips WHERE clip_id='ck-clip'").fetchone()
    assert row["content_kind"] == "sourced"


def test_quota_usage_provider_defaults_to_youtube(repo):
    repo.conn.execute(
        "INSERT INTO quota_usage (date, endpoint, units) VALUES ('2026-05-19', 'videos.insert', 1600)"
    )
    row = repo.conn.execute("SELECT provider FROM quota_usage WHERE date='2026-05-19'").fetchone()
    assert row["provider"] == "youtube"


# ---------------------------------------------------------------------------
# DAL helpers: insert_topic / seen_topics_in_window
# ---------------------------------------------------------------------------


def test_insert_topic_returns_id_and_row_is_findable(repo):
    topic_id = repo.insert_topic(
        url="https://example.com/1",
        title="GPT-5 Released",
        summary="OpenAI ships GPT-5.",
        source_feed="https://feeds.example.com",
        fetched_at="2026-05-19T10:00:00Z",
        published_at="2026-05-19T09:00:00Z",
    )
    assert isinstance(topic_id, int)
    row = repo.conn.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()
    assert row["url"] == "https://example.com/1"
    assert row["status"] == "unscripted"


def test_insert_topic_without_summary(repo):
    topic_id = repo.insert_topic(
        url="https://example.com/2",
        title="Llama 4 Benchmark",
        source_feed="https://feeds.example.com",
        fetched_at="2026-05-19T10:00:00Z",
    )
    row = repo.conn.execute("SELECT summary FROM topics WHERE id=?", (topic_id,)).fetchone()
    assert row["summary"] is None


def test_seen_topics_in_window_returns_rows_within_days(repo):
    repo.conn.execute(
        "INSERT INTO seen_topics (url_hash, title_normalized, first_seen_at) "
        "VALUES ('hash1', 'gpt five released', datetime('now', '-5 days'))"
    )
    repo.conn.execute(
        "INSERT INTO seen_topics (url_hash, title_normalized, first_seen_at) "
        "VALUES ('hash2', 'old news', datetime('now', '-40 days'))"
    )
    rows = repo.seen_topics_in_window(30)
    hashes = {r["url_hash"] for r in rows}
    assert "hash1" in hashes
    assert "hash2" not in hashes


# ---------------------------------------------------------------------------
# DAL helpers: mark_topic_scripted / mark_topic_expired
# ---------------------------------------------------------------------------


def test_mark_topic_scripted_transitions_status(repo):
    topic_id = repo.insert_topic(
        url="https://example.com/3", title="T", source_feed="F",
        fetched_at="2026-05-19T10:00:00Z",
    )
    repo.mark_topic_scripted(topic_id)
    row = repo.conn.execute("SELECT status FROM topics WHERE id=?", (topic_id,)).fetchone()
    assert row["status"] == "scripted"


def test_mark_topic_expired_transitions_status(repo):
    topic_id = repo.insert_topic(
        url="https://example.com/4", title="T", source_feed="F",
        fetched_at="2026-05-19T10:00:00Z",
    )
    repo.mark_topic_expired(topic_id)
    row = repo.conn.execute("SELECT status FROM topics WHERE id=?", (topic_id,)).fetchone()
    assert row["status"] == "expired"


# ---------------------------------------------------------------------------
# DAL helpers: insert_script / update_script_status
# ---------------------------------------------------------------------------


def _insert_sample_topic(repo: Repository) -> int:
    return repo.insert_topic(
        url="https://example.com/t", title="T", source_feed="F",
        fetched_at="2026-05-19T10:00:00Z",
    )


def test_insert_script_persists_row(repo):
    topic_id = _insert_sample_topic(repo)
    repo.insert_script(
        script_id="sc-uuid-1",
        topic_id=topic_id,
        title="GPT-5 Is Here",
        narration="OpenAI just dropped GPT-5 and it hits different.",
        shots_json='[{"index":0,"prompt":"p","duration_s":4}]',
        style_suffix="clean editorial",
        ollama_model="qwen2.5:3b-instruct",
        created_at="2026-05-19T10:05:00Z",
    )
    row = repo.conn.execute("SELECT * FROM scripts WHERE script_id='sc-uuid-1'").fetchone()
    assert row["title"] == "GPT-5 Is Here"
    assert row["status"] == "pending"


def test_update_script_status_changes_status_field(repo):
    topic_id = _insert_sample_topic(repo)
    repo.insert_script(
        script_id="sc-uuid-2", topic_id=topic_id,
        title="T", narration="N", shots_json="[]",
        style_suffix="s", ollama_model="m", created_at="2026-05-19T10:00:00Z",
    )
    repo.update_script_status("sc-uuid-2", "scripted")
    row = repo.conn.execute("SELECT status FROM scripts WHERE script_id='sc-uuid-2'").fetchone()
    assert row["status"] == "scripted"


def test_update_script_status_with_rejection_reason(repo):
    topic_id = _insert_sample_topic(repo)
    repo.insert_script(
        script_id="sc-uuid-3", topic_id=topic_id,
        title="T", narration="N", shots_json="[]",
        style_suffix="s", ollama_model="m", created_at="2026-05-19T10:00:00Z",
    )
    repo.update_script_status("sc-uuid-3", "rejected_policy", rejection_reason="banned token")
    row = repo.conn.execute("SELECT * FROM scripts WHERE script_id='sc-uuid-3'").fetchone()
    assert row["status"] == "rejected_policy"
    assert row["rejection_reason"] == "banned token"


# ---------------------------------------------------------------------------
# DAL helpers: clips_for_generation_run / get_clip_with_script
# ---------------------------------------------------------------------------


def _insert_ai_clip_with_script(repo: Repository, clip_id: str, script_id: str) -> None:
    topic_id = repo.insert_topic(
        url=f"https://example.com/{clip_id}", title="T", source_feed="F",
        fetched_at="2026-05-19T10:00:00Z",
    )
    repo.insert_script(
        script_id=script_id, topic_id=topic_id,
        title="GPT-5", narration="N", shots_json="[]",
        style_suffix="s", ollama_model="m", created_at="2026-05-19T10:00:00Z",
    )
    repo.conn.execute(
        "INSERT INTO clips (clip_id, start_s, end_s, hook, suggested_title, "
        "selection_method, content_kind, script_id, status) "
        "VALUES (?, 0.0, 16.0, 'H', 'T', 'ai_generated', 'ai_generated', ?, 'selected')",
        (clip_id, script_id),
    )


def test_clips_for_generation_run_returns_ai_generated_clips(repo):
    _insert_ai_clip_with_script(repo, "ai-c1", "sc-g1")
    # Insert a sourced clip that should NOT appear
    repo.conn.execute(
        "INSERT INTO clips (clip_id, start_s, end_s, hook, suggested_title, "
        "selection_method, content_kind, status) "
        "VALUES ('src-c1', 0.0, 5.0, 'H', 'T', 'heatmap_aided', 'sourced', 'quality_pass')"
    )
    clips = repo.clips_for_generation_run()
    ids = {r["clip_id"] for r in clips}
    assert "ai-c1" in ids
    assert "src-c1" not in ids


def test_get_clip_with_script_returns_joined_row(repo):
    _insert_ai_clip_with_script(repo, "ai-c2", "sc-g2")
    row = repo.get_clip_with_script("ai-c2")
    assert row is not None
    assert row["clip_id"] == "ai-c2"
    assert row["s_title"] == "GPT-5"


def test_get_clip_with_script_returns_none_for_missing(repo):
    assert repo.get_clip_with_script("no-such-clip") is None


# ---------------------------------------------------------------------------
# Regression: legacy sourced-clip upload body is unchanged post-migration
# ---------------------------------------------------------------------------


def test_legacy_sourced_clip_insert_body_unchanged():
    """content_kind column must not affect build_insert_body for sourced rows.

    This is the byte-identical regression AC from Ticket 01: adding
    content_kind='sourced' to the clips table must not change the upload
    resource body that daily_upload.py sends for legacy quality_pass clips.
    """
    from datetime import datetime, timezone
    from src.uploader.insert_body import build_insert_body

    class _Row(dict):
        pass

    row = _Row(
        hook="GPT-5 just landed",
        suggested_title="GPT-5 Just Dropped",
        video_id="legacy_vid",
        channel="TechChannel",
        keyword="ai_models",
        v_video_id="legacy_vid",
        v_channel="TechChannel",
        v_keyword="ai_models",
        content_kind="sourced",   # new column present but must be ignored
    )
    publish_at = datetime(2026, 5, 19, 9, 0, 0, tzinfo=timezone.utc)
    body = build_insert_body(clip_row=row, video_row=row, padded_publish_at_utc=publish_at)
    assert set(body.keys()) == {"snippet", "status"}
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["selfDeclaredMadeForKids"] is False


# ---------------------------------------------------------------------------
# DAL helpers: get_script (Slice 9)
# ---------------------------------------------------------------------------


def _insert_topic_and_script(repo) -> str:
    topic_id = repo.insert_topic(
        url="https://example.com/gs", title="T", source_feed="F",
        fetched_at="2026-05-22T10:00:00Z",
    )
    repo.insert_script(
        script_id="gs-script-1",
        topic_id=topic_id,
        title="GPT-5 Is Here",
        narration="AI is wild right now.",
        shots_json='[]',
        style_suffix="clean editorial",
        ollama_model="qwen2.5:3b-instruct",
        created_at="2026-05-22T10:00:00Z",
        category="ai-models",
    )
    return "gs-script-1"


def test_get_script_returns_row_for_known_id(repo):
    script_id = _insert_topic_and_script(repo)
    row = repo.get_script(script_id)
    assert row is not None
    assert row["script_id"] == script_id
    assert row["narration"] == "AI is wild right now."


def test_get_script_returns_none_for_unknown_id(repo):
    assert repo.get_script("nonexistent-id") is None
