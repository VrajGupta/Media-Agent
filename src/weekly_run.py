"""Phase 6 weekly_run orchestrator.

Sequential pipeline:
    discovery → downloader → lang_detect → selector → policy_gate
    → editor → quality_screen → slot_planner → retention

Each stage is invoked through a per-stage lambda adapter so we can call the
heterogeneous run_all signatures with one consistent failure-handling loop.

A `runs` row is opened at the start (kind='weekly') and closed at the end
with success=1 + a JSON summary. Exceptions raised by any stage are caught,
captured into the summary, and the row is closed with success=0 before
re-raising.

`--dry-run` policy (per Phase 6 plan):
  - discovery: dry_run=True (still spends quota, no DB writes)
  - downloader: SKIPPED entirely (no dry-run flag in the module)
  - lang_detect / selector / policy_gate / editor / quality_screen / slot_planner:
    dry_run=True propagated
  - retention: always dry_run=True (Phase 6 builds skeleton; Phase 7 enables
    real deletion)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Callable, List, Tuple

from loguru import logger

from src.config_loader import Config, load_config
from src.observability import append_alert, setup_logging
from src.state import Repository, connect


def _summarize(results: Any) -> Any:
    """Compress a stage's run_all result into a tiny dict for runs.summary_json."""
    if results is None:
        return None
    if isinstance(results, list):
        return {"count": len(results)}
    # Some stages return a dataclass-like object (e.g. retention).
    if hasattr(results, "__dict__"):
        return {k: v for k, v in vars(results).items() if not k.startswith("_")}
    return {"value": str(results)[:120]}


def _build_pipeline(
    cfg: Config,
    repo: Repository,
    *,
    dry_run: bool,
    youtube: Any,
    ledger: Any,
    ollama_host: str | None,
) -> List[Tuple[str, Callable[[], Any]]]:
    """Compose the pipeline as (name, callable) pairs. Each callable invokes
    the stage's run_all with the correct real signature."""
    # Lazy-import each stage so an import failure in one doesn't break the orchestrator.
    from src import discovery, downloader, lang_detect, selector
    from src import policy_gate, editor, quality_screen
    from src import slot_planner
    from src import retention

    pipeline: List[Tuple[str, Callable[[], Any]]] = [
        ("discovery",
         lambda: discovery.run_all(cfg, repo, ledger, youtube,
                                   force=False, dry_run=dry_run)),
        ("downloader",
         lambda: [] if dry_run else downloader.run_all(cfg, repo)),
        ("lang_detect",
         lambda: lang_detect.run_all(repo, cfg, dry_run=dry_run)),
        # ("captions", lambda: captions.run_all(repo, cfg, dry_run=dry_run)),  # Pivot.1
        ("selector",
         lambda: selector.run_all(repo, cfg, dry_run=dry_run)),
        ("policy_gate",
         lambda: policy_gate.run_all(repo, cfg, dry_run=dry_run, ollama_host=ollama_host)),
        ("editor",
         lambda: editor.run_all(repo, cfg, dry_run=dry_run)),
        ("quality_screen",
         lambda: quality_screen.run_all(repo, cfg, dry_run=dry_run)),
        ("slot_planner",
         lambda: slot_planner.run_all(repo, cfg, dry_run=dry_run)),
        ("retention",
         lambda: retention.run_all(repo, cfg, dry_run=True)),
    ]
    return pipeline


def run_weekly(
    *,
    repo: Repository,
    cfg: Config,
    dry_run: bool = False,
    youtube: Any = None,
    ledger: Any = None,
    ollama_host: str | None = None,
) -> Tuple[bool, dict]:
    """Run the weekly pipeline. Returns (success, summary)."""
    logs_dir = cfg.abs_path(cfg.paths.logs_dir)
    run_id = repo.start_run(kind="weekly")
    summary: dict[str, Any] = {"stages": {}, "dry_run": dry_run}
    pipeline = _build_pipeline(
        cfg, repo, dry_run=dry_run, youtube=youtube,
        ledger=ledger, ollama_host=ollama_host,
    )
    success = True
    try:
        for stage_name, stage_callable in pipeline:
            logger.info(f"weekly_run: stage={stage_name}")
            results = stage_callable()
            summary["stages"][stage_name] = _summarize(results)
        repo.finish_run(run_id, success=True, summary_json=json.dumps(summary))
        append_alert(
            logs_dir, kind="weekly_run_finished",
            message=f"weekly_run finished; stages={list(summary['stages'].keys())}",
        )
    except Exception as exc:
        success = False
        summary["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        repo.finish_run(run_id, success=False, summary_json=json.dumps(summary))
        append_alert(
            logs_dir, kind="weekly_run_failed",
            message=summary["error"],
        )
        raise
    return (success, summary)


def main() -> int:
    parser = argparse.ArgumentParser(prog="src.weekly_run")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Propagate dry-run through stages that support it. NOTE: discovery "
            "still spends YouTube quota; downloader is skipped entirely "
            "(no per-stage flag); Whisper/Ollama/ffprobe still execute where "
            "stages reach them — only persistent side effects are suppressed."
        ),
    )
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.abs_path(cfg.paths.logs_dir))

    db_path = cfg.abs_path(cfg.paths.state_db)
    if not db_path.exists():
        logger.error(
            f"state.db not found at {db_path}. "
            f"Run `python -m src.bootstrap --init-db` first."
        )
        return 1

    conn = connect(db_path)
    repo = Repository(conn)

    try:
        # Build expensive shared clients once for the whole run.
        from src.integrations.youtube import build_youtube_client
        from src.quota_ledger import QuotaLedger
        youtube = build_youtube_client(cfg)
        ledger = QuotaLedger(repo.conn, ceiling_units=int(cfg.youtube_quota_ceiling_units))
        ollama_host = os.environ.get("OLLAMA_HOST")

        success, summary = run_weekly(
            repo=repo, cfg=cfg, dry_run=args.dry_run,
            youtube=youtube, ledger=ledger, ollama_host=ollama_host,
        )
        print(json.dumps(summary, indent=2))
        return 0 if success else 1
    except Exception:
        # Already alerted + run row closed inside run_weekly. Re-raise printed
        # to stderr by the interpreter is fine; CLI exits non-zero.
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
