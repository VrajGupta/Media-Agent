"""Phase 7 migration script tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts.drop_gameplay_tables import drop_gameplay_tables


def _seed_db_with_gameplay_tables(db_path: Path) -> None:
    """Recreate the legacy gameplay schema (Phase 7 removes from main schema.sql)."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS gameplay_cursor ("
            "    file_name TEXT PRIMARY KEY,"
            "    last_offset_s REAL NOT NULL DEFAULT 0,"
            "    file_duration_s REAL,"
            "    last_used_at TEXT"
            ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS gameplay_pointer ("
            "    id INTEGER PRIMARY KEY CHECK (id = 1),"
            "    next_index INTEGER NOT NULL DEFAULT 0"
            ")"
        )
        conn.execute(
            "INSERT OR IGNORE INTO gameplay_pointer (id, next_index) VALUES (1, 0)"
        )
        conn.execute(
            "INSERT INTO gameplay_cursor (file_name, last_offset_s) VALUES (?, ?)",
            ("subway.mp4", 30.0),
        )
        conn.commit()
    finally:
        conn.close()


def _table_exists(db_path: Path, name: str) -> bool:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def test_dry_run_reports_counts_without_drop(tmp_path):
    db = tmp_path / "state.db"
    _seed_db_with_gameplay_tables(db)
    counts = drop_gameplay_tables(db, dry_run=True)
    assert counts["gameplay_cursor"] == 1
    assert counts["gameplay_pointer"] == 1
    # Tables still present after dry-run.
    assert _table_exists(db, "gameplay_cursor")
    assert _table_exists(db, "gameplay_pointer")


def test_real_run_drops_tables(tmp_path):
    db = tmp_path / "state.db"
    _seed_db_with_gameplay_tables(db)
    counts = drop_gameplay_tables(db, dry_run=False)
    # Counts reported pre-drop.
    assert counts["gameplay_cursor"] == 1
    assert counts["gameplay_pointer"] == 1
    # Tables gone after real run.
    assert not _table_exists(db, "gameplay_cursor")
    assert not _table_exists(db, "gameplay_pointer")


def test_idempotent_on_already_dropped_db(tmp_path):
    db = tmp_path / "state.db"
    # Empty DB — no gameplay tables ever existed.
    sqlite3.connect(str(db)).close()
    counts = drop_gameplay_tables(db, dry_run=False)
    assert counts["gameplay_cursor"] == 0
    assert counts["gameplay_pointer"] == 0
    assert not _table_exists(db, "gameplay_cursor")
    assert not _table_exists(db, "gameplay_pointer")
