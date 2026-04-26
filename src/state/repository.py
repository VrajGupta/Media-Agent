from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_FILE = Path(__file__).parent / "schema.sql"


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    sql = SCHEMA_FILE.read_text()
    conn.executescript(sql)


class Repository:
    """Thin DAL. Each stage uses the methods relevant to it; no ORM."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            self.conn.execute("BEGIN")
            yield self.conn
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    # ---- videos ----

    def upsert_video(self, **fields) -> None:
        cols = ", ".join(fields.keys())
        placeholders = ", ".join(f":{k}" for k in fields)
        update_clause = ", ".join(f"{k}=excluded.{k}" for k in fields if k != "video_id")
        self.conn.execute(
            f"INSERT INTO videos ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(video_id) DO UPDATE SET {update_clause}, updated_at=datetime('now')",
            fields,
        )

    def set_video_status(self, video_id: str, status: str, reason: str | None = None) -> None:
        self.conn.execute(
            "UPDATE videos SET status=?, rejection_reason=?, updated_at=datetime('now') WHERE video_id=?",
            (status, reason, video_id),
        )

    def videos_by_status(self, status: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM videos WHERE status=?", (status,)).fetchall()

    # ---- clips ----

    def insert_clip(self, **fields) -> None:
        cols = ", ".join(fields.keys())
        placeholders = ", ".join(f":{k}" for k in fields)
        self.conn.execute(
            f"INSERT OR REPLACE INTO clips ({cols}) VALUES ({placeholders})", fields
        )

    def set_clip_status(
        self,
        clip_id: str,
        status: str,
        reason: str | None = None,
        **extra,
    ) -> None:
        sets = ["status=?", "rejection_reason=?", "updated_at=datetime('now')"]
        params: list = [status, reason]
        for k, v in extra.items():
            sets.append(f"{k}=?")
            params.append(v)
        params.append(clip_id)
        self.conn.execute(
            f"UPDATE clips SET {', '.join(sets)} WHERE clip_id=?",
            params,
        )

    def clips_by_status(self, status: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM clips WHERE status=?", (status,)).fetchall()

    # ---- runs ----

    def start_run(self, kind: str) -> int:
        cur = self.conn.execute("INSERT INTO runs (kind) VALUES (?)", (kind,))
        return cur.lastrowid

    def finish_run(self, run_id: int, success: bool, summary_json: str) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=datetime('now'), success=?, summary_json=? WHERE run_id=?",
            (1 if success else 0, summary_json, run_id),
        )
