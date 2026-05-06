"""weekly_run orchestrator tests — pipeline + signature + run row.

Mocks every stage's run_all so the test can assert each was called with the
correct real signature without invoking Whisper, ffmpeg, Ollama, or any
network.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.state import Repository, connect, initialize_schema
from src.weekly_run import run_weekly

from tests.conftest import StubConfig


def _new_repo(tmp_path) -> Repository:
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def test_happy_path_calls_each_stage(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    youtube_obj = object()
    ledger_obj = object()
    with patch("src.discovery.run_all", return_value=[]) as p_disc, \
         patch("src.downloader.run_all", return_value=[]) as p_dl, \
         patch("src.lang_detect.run_all", return_value=[]) as p_lang, \
         patch("src.selector.run_all", return_value=[]) as p_sel, \
         patch("src.policy_gate.run_all", return_value=[]) as p_gate, \
         patch("src.editor.run_all", return_value=[]) as p_ed, \
         patch("src.quality_screen.run_all", return_value=[]) as p_qs, \
         patch("src.slot_planner.run_all", return_value=[]) as p_sp, \
         patch("src.retention.run_all", return_value=MagicMock(dry_run=True)) as p_ret:

        success, summary = run_weekly(
            repo=repo, cfg=cfg, dry_run=False,
            youtube=youtube_obj, ledger=ledger_obj, ollama_host="http://x:11434",
        )

    assert success is True
    assert "stages" in summary
    # Each stage was invoked with the verified real signature.
    p_disc.assert_called_once_with(cfg, repo, ledger_obj, youtube_obj,
                                   force=False, dry_run=False)
    p_dl.assert_called_once_with(cfg, repo)   # no dry_run kwarg
    p_lang.assert_called_once_with(repo, cfg, dry_run=False)
    p_sel.assert_called_once_with(repo, cfg, dry_run=False)
    p_gate.assert_called_once_with(repo, cfg, dry_run=False, ollama_host="http://x:11434")
    p_ed.assert_called_once_with(repo, cfg, dry_run=False)
    p_qs.assert_called_once_with(repo, cfg, dry_run=False)
    p_sp.assert_called_once_with(repo, cfg, dry_run=False)
    p_ret.assert_called_once_with(repo, cfg, dry_run=True)


def test_dry_run_skips_downloader(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    with patch("src.discovery.run_all", return_value=[]) as p_disc, \
         patch("src.downloader.run_all", return_value=[]) as p_dl, \
         patch("src.lang_detect.run_all", return_value=[]), \
         patch("src.selector.run_all", return_value=[]), \
         patch("src.policy_gate.run_all", return_value=[]), \
         patch("src.editor.run_all", return_value=[]), \
         patch("src.quality_screen.run_all", return_value=[]), \
         patch("src.slot_planner.run_all", return_value=[]), \
         patch("src.retention.run_all", return_value=MagicMock(dry_run=True)):

        success, summary = run_weekly(
            repo=repo, cfg=cfg, dry_run=True,
            youtube=object(), ledger=object(),
        )

    assert success is True
    # Discovery still called with dry_run=True (quota spent, no DB writes).
    p_disc.assert_called_once()
    args, kwargs = p_disc.call_args
    assert kwargs["dry_run"] is True
    # Downloader NOT called under --dry-run (no per-stage flag).
    p_dl.assert_not_called()


def test_finished_alert_written_on_success(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    with patch("src.discovery.run_all", return_value=[]), \
         patch("src.downloader.run_all", return_value=[]), \
         patch("src.lang_detect.run_all", return_value=[]), \
         patch("src.selector.run_all", return_value=[]), \
         patch("src.policy_gate.run_all", return_value=[]), \
         patch("src.editor.run_all", return_value=[]), \
         patch("src.quality_screen.run_all", return_value=[]), \
         patch("src.slot_planner.run_all", return_value=[]), \
         patch("src.retention.run_all", return_value=MagicMock(dry_run=True)):
        run_weekly(repo=repo, cfg=cfg, youtube=object(), ledger=object())

    alerts_md = (Path(cfg.paths.logs_dir) / "alerts.md").read_text()
    assert "weekly_run_finished" in alerts_md


def test_runs_row_written_on_success_with_json_string(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    with patch("src.discovery.run_all", return_value=[1, 2, 3]), \
         patch("src.downloader.run_all", return_value=[]), \
         patch("src.lang_detect.run_all", return_value=[]), \
         patch("src.selector.run_all", return_value=[]), \
         patch("src.policy_gate.run_all", return_value=[]), \
         patch("src.editor.run_all", return_value=[]), \
         patch("src.quality_screen.run_all", return_value=[]), \
         patch("src.slot_planner.run_all", return_value=[]), \
         patch("src.retention.run_all", return_value=MagicMock(dry_run=True)):
        run_weekly(repo=repo, cfg=cfg, youtube=object(), ledger=object())

    row = repo.conn.execute(
        "SELECT kind, success, summary_json FROM runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    assert row["kind"] == "weekly"
    assert row["success"] == 1
    # summary_json is a STRING (regression on the actual finish_run helper).
    assert isinstance(row["summary_json"], str)
    parsed = json.loads(row["summary_json"])
    assert parsed["stages"]["discovery"] == {"count": 3}


def test_stage_failure_halts_and_records_error(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)

    def _boom(*args, **kwargs):
        raise RuntimeError("selector blew up")

    with patch("src.discovery.run_all", return_value=[]), \
         patch("src.downloader.run_all", return_value=[]), \
         patch("src.lang_detect.run_all", return_value=[]), \
         patch("src.selector.run_all", side_effect=_boom), \
         patch("src.policy_gate.run_all") as p_gate, \
         patch("src.editor.run_all"), \
         patch("src.quality_screen.run_all"), \
         patch("src.slot_planner.run_all"), \
         patch("src.retention.run_all"):
        with pytest.raises(RuntimeError):
            run_weekly(repo=repo, cfg=cfg, youtube=object(), ledger=object())

    p_gate.assert_not_called()   # later stages never reached
    row = repo.conn.execute(
        "SELECT kind, success, summary_json FROM runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    assert row["kind"] == "weekly"
    assert row["success"] == 0
    parsed = json.loads(row["summary_json"])
    assert "RuntimeError" in parsed["error"]
    assert "selector blew up" in parsed["error"]
    # Failure alert appended.
    alerts_md = (Path(cfg.paths.logs_dir) / "alerts.md").read_text()
    assert "weekly_run_failed" in alerts_md


def test_finish_run_receives_string_not_dict(tmp_path):
    """Regression on the actual existing repository helper."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    with patch.object(Repository, "finish_run") as p_finish, \
         patch("src.discovery.run_all", return_value=[]), \
         patch("src.downloader.run_all", return_value=[]), \
         patch("src.lang_detect.run_all", return_value=[]), \
         patch("src.selector.run_all", return_value=[]), \
         patch("src.policy_gate.run_all", return_value=[]), \
         patch("src.editor.run_all", return_value=[]), \
         patch("src.quality_screen.run_all", return_value=[]), \
         patch("src.slot_planner.run_all", return_value=[]), \
         patch("src.retention.run_all", return_value=MagicMock(dry_run=True)):
        run_weekly(repo=repo, cfg=cfg, youtube=object(), ledger=object())

    args, kwargs = p_finish.call_args
    # finish_run(run_id, success=True, summary_json=<str>)
    assert isinstance(kwargs["summary_json"], str)
    json.loads(kwargs["summary_json"])  # parses cleanly
