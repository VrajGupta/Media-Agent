"""Pivot.6 idempotent schema migration.

Adds the four new Pivot.6 tables (topics, seen_topics, scripts, generation_jobs),
three new columns (clips.content_kind, clips.script_id, quota_usage.provider),
and relaxes clips.video_id from NOT NULL to nullable via a table rebuild.

Safe to re-run: every operation is guarded by an existence check.

Usage:
    python -m scripts.migrate_pivot_6_3 [--db data/state.db] [--dry-run]

Exit codes:
    0  ok / already up-to-date
    1  db not found
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(
        r["name"] == column
        for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
    )


def _column_notnull(conn: sqlite3.Connection, table: str, column: str) -> bool:
    for r in conn.execute(f"PRAGMA table_info({table})").fetchall():
        if r["name"] == column:
            return bool(r["notnull"])
    return False


# ---------------------------------------------------------------------------
# Public migration function (injectable in tests)
# ---------------------------------------------------------------------------


def migrate(conn: sqlite3.Connection, dry_run: bool = False) -> list[str]:
    """Apply Pivot.6 schema changes to `conn`. Returns list of applied ops.

    Idempotent: each operation is only applied if the target state is not
    already present. `dry_run=True` returns the planned ops without applying.
    """
    conn.row_factory = sqlite3.Row
    ops: list[str] = []

    def _apply(label: str, fn) -> None:
        ops.append(label)
        if not dry_run:
            fn()

    # ---- Step 1: new tables ----

    if not _table_exists(conn, "topics"):
        _apply("CREATE TABLE topics", lambda: conn.executescript("""
            CREATE TABLE topics (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                url              TEXT NOT NULL,
                title            TEXT NOT NULL,
                summary          TEXT,
                source_feed      TEXT NOT NULL,
                fetched_at       TEXT NOT NULL,
                published_at     TEXT,
                status           TEXT NOT NULL DEFAULT 'unscripted',
                topic_score_json TEXT,
                weighted_score   REAL,
                category         TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_topics_status     ON topics(status);
            CREATE INDEX IF NOT EXISTS idx_topics_fetched_at ON topics(fetched_at);
        """))

    if not _table_exists(conn, "seen_topics"):
        _apply("CREATE TABLE seen_topics", lambda: conn.execute("""
            CREATE TABLE seen_topics (
                url_hash         TEXT PRIMARY KEY,
                title_normalized TEXT NOT NULL,
                first_seen_at    TEXT NOT NULL
            )
        """))

    if not _table_exists(conn, "scripts"):
        _apply("CREATE TABLE scripts", lambda: conn.executescript("""
            CREATE TABLE scripts (
                script_id          TEXT PRIMARY KEY,
                topic_id           INTEGER NOT NULL REFERENCES topics(id),
                title              TEXT NOT NULL,
                narration          TEXT NOT NULL,
                shots_json         TEXT NOT NULL,
                style_suffix       TEXT NOT NULL,
                ollama_model       TEXT NOT NULL,
                topic_score_json   TEXT,
                category           TEXT,
                quality_score_json TEXT,
                quality_score      REAL,
                rejection_reason   TEXT,
                created_at         TEXT NOT NULL,
                status             TEXT NOT NULL DEFAULT 'pending'
            );
            CREATE INDEX IF NOT EXISTS idx_scripts_status   ON scripts(status);
            CREATE INDEX IF NOT EXISTS idx_scripts_topic_id ON scripts(topic_id);
        """))

    if not _table_exists(conn, "generation_jobs"):
        _apply("CREATE TABLE generation_jobs", lambda: conn.executescript("""
            CREATE TABLE generation_jobs (
                job_id       TEXT PRIMARY KEY,
                script_id    TEXT NOT NULL REFERENCES scripts(script_id),
                shot_index   INTEGER NOT NULL,
                provider     TEXT NOT NULL,
                prompt       TEXT NOT NULL,
                duration_s   INTEGER NOT NULL,
                status       TEXT NOT NULL,
                external_id  TEXT,
                output_path  TEXT,
                cost_cents   INTEGER,
                submitted_at TEXT,
                completed_at TEXT,
                error        TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_generation_jobs_script_id
                ON generation_jobs(script_id);
        """))

    # ---- Step 2: new columns on existing tables ----

    if not _column_exists(conn, "clips", "content_kind"):
        _apply("ALTER clips ADD content_kind", lambda: conn.execute(
            "ALTER TABLE clips ADD COLUMN content_kind TEXT NOT NULL DEFAULT 'sourced'"
        ))

    if not _column_exists(conn, "clips", "script_id"):
        _apply("ALTER clips ADD script_id", lambda: conn.execute(
            "ALTER TABLE clips ADD COLUMN script_id TEXT"
        ))

    if not _column_exists(conn, "quota_usage", "provider"):
        _apply("ALTER quota_usage ADD provider", lambda: conn.execute(
            "ALTER TABLE quota_usage ADD COLUMN provider TEXT NOT NULL DEFAULT 'youtube'"
        ))

    # ---- Step 3: relax clips.video_id to nullable (table rebuild) ----

    if _table_exists(conn, "clips") and _column_notnull(conn, "clips", "video_id"):
        _apply("rebuild clips (video_id nullable)", lambda: _rebuild_clips_nullable(conn))

    return ops


def _rebuild_clips_nullable(conn: sqlite3.Connection) -> None:
    """Replace the clips table with one where video_id is nullable.

    Dynamically maps old columns → new columns so the rebuild works regardless
    of which optional clips columns (title_slug, publish_at_utc, etc.) already
    exist in the source table. Columns missing from the source get NULL defaults.
    content_kind and script_id are added if not already present.
    """
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(clips)").fetchall()}

    # All desired columns in the new table, in order:
    #   (name, definition, select_expr_from_old)
    new_cols: list[tuple[str, str, str]] = [
        ("clip_id",            "TEXT PRIMARY KEY",                     "clip_id"),
        ("video_id",           "TEXT",                                 "video_id"),
        ("start_s",            "REAL NOT NULL",                        "start_s"),
        ("end_s",              "REAL NOT NULL",                        "end_s"),
        ("hook",               "TEXT NOT NULL",                        "hook"),
        ("suggested_title",    "TEXT NOT NULL",                        "suggested_title"),
        ("title_slug",         "TEXT",                                 "title_slug" if "title_slug" in existing else "NULL"),
        ("selection_method",   "TEXT NOT NULL",                        "selection_method"),
        ("publish_at_utc",     "TEXT",                                 "publish_at_utc" if "publish_at_utc" in existing else "NULL"),
        ("publish_slot_local", "TEXT",                                 "publish_slot_local" if "publish_slot_local" in existing else "NULL"),
        ("output_path",        "TEXT",                                 "output_path" if "output_path" in existing else "NULL"),
        ("youtube_video_id",   "TEXT",                                 "youtube_video_id" if "youtube_video_id" in existing else "NULL"),
        ("content_kind",       "TEXT NOT NULL DEFAULT 'sourced'",      "content_kind" if "content_kind" in existing else "'sourced'"),
        ("script_id",          "TEXT",                                 "script_id" if "script_id" in existing else "NULL"),
        ("status",             "TEXT NOT NULL",                        "status"),
        ("rejection_reason",   "TEXT",                                 "rejection_reason" if "rejection_reason" in existing else "NULL"),
        ("created_at",         "TEXT NOT NULL DEFAULT (datetime('now'))", "created_at"),
        ("updated_at",         "TEXT NOT NULL DEFAULT (datetime('now'))", "updated_at"),
    ]

    col_defs = ",\n            ".join(f"{name} {defn}" for name, defn, _ in new_cols)
    select_exprs = ", ".join(expr for _, _, expr in new_cols)
    target_names = ", ".join(name for name, _, _ in new_cols)

    conn.executescript(f"""
        PRAGMA foreign_keys = OFF;

        CREATE TABLE clips_pivot6_new (
            {col_defs}
        );

        INSERT INTO clips_pivot6_new ({target_names})
        SELECT {select_exprs} FROM clips;

        DROP TABLE clips;
        ALTER TABLE clips_pivot6_new RENAME TO clips;

        CREATE INDEX IF NOT EXISTS idx_clips_status         ON clips(status);
        CREATE INDEX IF NOT EXISTS idx_clips_video_id       ON clips(video_id);
        CREATE INDEX IF NOT EXISTS idx_clips_publish_at_utc ON clips(publish_at_utc);

        PRAGMA foreign_keys = ON;
    """)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(prog="scripts.migrate_pivot_6_3")
    parser.add_argument("--db", default="data/state.db", help="Path to state.db")
    parser.add_argument("--dry-run", action="store_true", help="Report planned ops, don't apply")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"state.db not found at {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        ops = migrate(conn, dry_run=args.dry_run)
        label = "dry-run" if args.dry_run else "applied"
        if ops:
            print(f"Pivot.6 migration ({label}):")
            for op in ops:
                print(f"  {op}")
        else:
            print("Pivot.6 migration: already up-to-date, nothing to do.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
