"""Phase 7 one-shot migration: drop gameplay_cursor + gameplay_pointer.

These tables were retained in schema.sql for back-compat after Pivot.3
dropped the split-screen + gameplay-rotation editor. Phase 7 removed the
DDL from schema.sql; this script removes the tables from any pre-existing
populated state.db.

After running once, the tables are gone and the schema.sql is clean. The
script is idempotent — running again is a no-op.

Usage:
    python -m scripts.drop_gameplay_tables --config config.yaml [--dry-run]

Exit codes:
    0  ok
    1  state.db missing
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


# Allow running as `python -m scripts.drop_gameplay_tables` from the project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config_loader import load_config  # noqa: E402


_TABLES = ("gameplay_cursor", "gameplay_pointer")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _row_count(conn: sqlite3.Connection, name: str) -> int:
    if not _table_exists(conn, name):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])


def drop_gameplay_tables(db_path: str | Path, *, dry_run: bool = False) -> dict:
    """Drop the gameplay tables from `db_path`. Returns {table: pre_count} for
    every table found (regardless of dry_run)."""
    db_path = Path(db_path)
    counts: dict[str, int] = {}
    conn = sqlite3.connect(str(db_path))
    try:
        for tbl in _TABLES:
            if _table_exists(conn, tbl):
                counts[tbl] = _row_count(conn, tbl)
            else:
                counts[tbl] = 0
        if dry_run:
            return counts
        for tbl in _TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {tbl}")
        conn.commit()
        return counts
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(prog="scripts.drop_gameplay_tables")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report counts without dropping",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    db_path = cfg.abs_path(cfg.paths.state_db)
    if not db_path.exists():
        print(f"state.db not found at {db_path}", file=sys.stderr)
        return 1

    counts = drop_gameplay_tables(db_path, dry_run=args.dry_run)
    label = "dry-run" if args.dry_run else "dropped"
    print(f"gameplay tables ({label}):")
    for tbl, n in counts.items():
        print(f"  {tbl}: {n} row(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
