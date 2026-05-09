"""Phase 7 per-run summary writer.

Appends one row per weekly_run / daily_upload invocation to logs/runs.md.
The runs table in SQLite still holds the canonical record (started/finished
+ summary_json); runs.md is a human-skimmable counterpart that stays
visible in Explorer alongside agent.log + alerts.md.

Best-effort, not concurrency-safe across processes. The Phase 7 run lock
serializes weekly_run + daily_upload at the entrypoint level, so two
writers can't actually contend on the happy path.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

RUNS_HEADER = (
    "| kind | started_at | finished_at | success | summary |\n"
    "| --- | --- | --- | --- | --- |\n"
)


def _format_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _sanitize(s: str) -> str:
    """Escape pipes and collapse newlines so the row stays on one markdown line."""
    return s.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def append_run_row(
    logs_dir: str | Path,
    *,
    kind: str,
    started_at: datetime,
    finished_at: datetime,
    success: bool,
    summary: str,
) -> None:
    """Append one row to logs/runs.md. Creates the file with a header if missing.

    Best-effort: this writer relies on Python's file-write atomicity and the
    Phase 7 run lock for safety. Cross-process contention is not handled
    here — the run lock is the contract.
    """
    logs_dir = Path(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    runs_path = logs_dir / "runs.md"
    if not runs_path.exists():
        runs_path.write_text("# Runs\n\n" + RUNS_HEADER, encoding="utf-8")

    row = (
        f"| {_sanitize(kind)} "
        f"| {_format_ts(started_at)} "
        f"| {_format_ts(finished_at)} "
        f"| {'true' if success else 'false'} "
        f"| {_sanitize(summary)} |\n"
    )
    with runs_path.open("a", encoding="utf-8") as f:
        f.write(row)
