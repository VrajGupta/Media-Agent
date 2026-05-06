"""bootstrap --smoke argparse + happy-path tests.

The smoke test orchestrates the full pipeline. We mock every stage's
runner so the test doesn't need YouTube OAuth, Whisper, or ffmpeg.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.bootstrap import main as bootstrap_main


def test_smoke_requires_keyword(monkeypatch, tmp_path):
    """`--smoke` without `--keyword` exits 2."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("# placeholder; load_config is mocked in this test")
    monkeypatch.setattr("sys.argv", ["bootstrap", "--smoke", "--config", str(cfg_path)])

    fake_cfg = MagicMock()
    with patch("src.bootstrap.load_config", return_value=fake_cfg):
        rc = bootstrap_main()
    assert rc == 2


def test_smoke_runs_pipeline_with_keyword(monkeypatch, tmp_path):
    """`--smoke --keyword X` calls each stage and returns 0 on success."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("placeholder")
    db_path = tmp_path / "state.db"
    db_path.touch()

    fake_cfg = MagicMock()
    fake_cfg.abs_path.return_value = db_path
    fake_cfg.paths.state_db = str(db_path)
    fake_cfg.paths.logs_dir = str(tmp_path / "logs")
    fake_cfg.youtube_quota_ceiling_units = 9000

    fake_kr = MagicMock(inserted=1, fetched=1, skipped=False)

    with patch("src.bootstrap.load_config", return_value=fake_cfg), \
         patch("src.bootstrap.connect"), \
         patch("src.bootstrap.Repository") as MockRepo, \
         patch("src.integrations.youtube.build_youtube_client", return_value=MagicMock()), \
         patch("src.quota_ledger.QuotaLedger", return_value=MagicMock()), \
         patch("src.observability.setup_logging"), \
         patch("src.discovery.run_for_keyword", return_value=fake_kr) as p_disc, \
         patch("src.downloader.run_all", return_value=[]) as p_dl, \
         patch("src.lang_detect.run_all", return_value=[]) as p_lang, \
         patch("src.selector.run_all", return_value=[]) as p_sel, \
         patch("src.policy_gate.run_all", return_value=[]) as p_gate, \
         patch("src.editor.run_all", return_value=[]) as p_ed, \
         patch("src.quality_screen.run_all", return_value=[]) as p_qs:

        # No quality_pass clip in DB → smoke ends gracefully at step 8.
        MockRepo.return_value.conn.execute.return_value.fetchone.return_value = None

        monkeypatch.setattr("sys.argv", [
            "bootstrap", "--smoke", "--keyword", "iconic movie moments",
            "--config", str(cfg_path),
        ])
        rc = bootstrap_main()

    assert rc == 0
    p_disc.assert_called_once()
    p_dl.assert_called_once()
    p_lang.assert_called_once()
    p_sel.assert_called_once()
    p_gate.assert_called_once()
    p_ed.assert_called_once()
    p_qs.assert_called_once()


def test_smoke_returns_1_on_stage_failure(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("placeholder")
    db_path = tmp_path / "state.db"
    db_path.touch()

    fake_cfg = MagicMock()
    fake_cfg.abs_path.return_value = db_path
    fake_cfg.paths.state_db = str(db_path)
    fake_cfg.paths.logs_dir = str(tmp_path / "logs")
    fake_cfg.youtube_quota_ceiling_units = 9000

    with patch("src.bootstrap.load_config", return_value=fake_cfg), \
         patch("src.bootstrap.connect"), \
         patch("src.bootstrap.Repository"), \
         patch("src.integrations.youtube.build_youtube_client", return_value=MagicMock()), \
         patch("src.quota_ledger.QuotaLedger", return_value=MagicMock()), \
         patch("src.observability.setup_logging"), \
         patch("src.discovery.run_for_keyword",
               side_effect=RuntimeError("disco kapow")):

        monkeypatch.setattr("sys.argv", [
            "bootstrap", "--smoke", "--keyword", "movies",
            "--config", str(cfg_path),
        ])
        rc = bootstrap_main()

    assert rc == 1


def test_check_path_unchanged(monkeypatch, tmp_path):
    """Existing --check path still works without --smoke flags interfering."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("placeholder")
    fake_cfg = MagicMock()

    with patch("src.bootstrap.load_config", return_value=fake_cfg), \
         patch("src.bootstrap.run_checks", return_value=0) as p_run_checks:
        monkeypatch.setattr("sys.argv", ["bootstrap", "--check",
                                         "--config", str(cfg_path)])
        rc = bootstrap_main()
    assert rc == 0
    p_run_checks.assert_called_once_with(fake_cfg)


def test_init_db_path_unchanged(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("placeholder")
    fake_cfg = MagicMock()

    with patch("src.bootstrap.load_config", return_value=fake_cfg), \
         patch("src.bootstrap.init_db") as p_init:
        monkeypatch.setattr("sys.argv", ["bootstrap", "--init-db",
                                         "--config", str(cfg_path)])
        rc = bootstrap_main()
    assert rc == 0
    p_init.assert_called_once_with(fake_cfg)
