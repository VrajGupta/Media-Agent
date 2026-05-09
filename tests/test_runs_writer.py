"""Phase 7 tests for logs/runs.md per-run summary writer.

The writer is best-effort, not concurrency-safe across processes. The Phase 7
run lock serializes weekly_run + daily_upload at the entrypoint level.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from src.observability.runs_writer import append_run_row


def _read(p):
    return p.read_text(encoding="utf-8")


def test_append_creates_file_with_header(tmp_path):
    started = datetime(2026, 5, 8, 2, 0, 11, tzinfo=timezone.utc)
    finished = datetime(2026, 5, 8, 2, 54, 33, tzinfo=timezone.utc)
    append_run_row(
        tmp_path, kind="weekly", started_at=started, finished_at=finished,
        success=True, summary="discovery=27, downloader=4, selector=4",
    )
    content = _read(tmp_path / "runs.md")
    assert content.startswith("# Runs")
    assert "| kind | started_at | finished_at | success | summary |" in content
    assert "| weekly |" in content
    assert "2026-05-08 02:00:11" in content
    assert "2026-05-08 02:54:33" in content
    assert "true" in content
    assert "discovery=27" in content


def test_append_adds_row_after_existing_rows(tmp_path):
    base = datetime(2026, 5, 8, 9, 0, 0, tzinfo=timezone.utc)
    append_run_row(
        tmp_path, kind="weekly", started_at=base, finished_at=base,
        success=True, summary="ok1",
    )
    append_run_row(
        tmp_path, kind="daily", started_at=base, finished_at=base,
        success=False, summary="ok2",
    )
    content = _read(tmp_path / "runs.md")
    # Header appears exactly once.
    assert content.count("| kind | started_at |") == 1
    assert "| weekly |" in content
    assert "| daily |" in content
    assert "false" in content


def test_summary_pipes_escaped(tmp_path):
    base = datetime(2026, 5, 8, tzinfo=timezone.utc)
    append_run_row(
        tmp_path, kind="weekly", started_at=base, finished_at=base,
        success=True, summary="stage_a=1 | stage_b=2",
    )
    content = _read(tmp_path / "runs.md")
    # The pipe inside summary must be escaped so the markdown row stays well-formed.
    assert "stage_a=1 \\| stage_b=2" in content


def test_summary_newlines_stripped(tmp_path):
    base = datetime(2026, 5, 8, tzinfo=timezone.utc)
    append_run_row(
        tmp_path, kind="daily", started_at=base, finished_at=base,
        success=True, summary="line1\nline2\r\nline3",
    )
    content = _read(tmp_path / "runs.md")
    daily_row = [l for l in content.splitlines() if "| daily |" in l][0]
    assert "line1 line2  line3" in daily_row  # newlines collapsed to spaces


def test_best_effort_append_in_process(tmp_path):
    """In-process two-thread append against a pre-existing file:
    Python GIL + open('a') makes both rows land.

    Cross-process safety AND the first-write-creates-header race are the
    run lock's job, NOT this writer. The Phase 7 run lock serializes
    weekly_run + daily_upload, so concurrent appends only happen against
    a file that was created by an earlier serialized run.
    """
    base = datetime(2026, 5, 8, tzinfo=timezone.utc)
    # Pre-create the file so we exercise the append path only.
    append_run_row(
        tmp_path, kind="weekly", started_at=base, finished_at=base,
        success=True, summary="seed",
    )

    def worker(tag: str):
        append_run_row(
            tmp_path, kind="weekly", started_at=base, finished_at=base,
            success=True, summary=f"tag={tag}",
        )

    threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    content = _read(tmp_path / "runs.md")
    for i in range(2):
        assert f"tag=t{i}" in content
    # Header preserved exactly once.
    assert content.count("| kind | started_at |") == 1
