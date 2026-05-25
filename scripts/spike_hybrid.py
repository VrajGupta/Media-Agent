"""Throwaway end-to-end hybrid spike (Pivot.7 / P7.6).

One real topic → tagged shots → hybrid routing → Kokoro → assemble → output/pending/.
Operator validates visuals, voice, and cost manually.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from loguru import logger

from src.config_loader import load_config
from src.gen_run import _generate_clip
from src.observability import setup_logging
from src.scripter.ollama_fns import make_script_generator
from src.scripter.runner import generate_script
from src.state import Repository, connect


def main() -> int:
    parser = argparse.ArgumentParser(description="Pivot.7 hybrid spike runner")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--topic-id", type=int, help="topics.id to script (default: latest unscripted)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.abs_path(cfg.paths.logs_dir))
    conn = connect(cfg.abs_path(cfg.paths.state_db))
    repo = Repository(conn)

    if args.topic_id:
        row = conn.execute("SELECT * FROM topics WHERE id=?", (args.topic_id,)).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM topics WHERE status='unscripted' ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        logger.error("No topic found")
        return 1

    topic = dict(row)
    generator = make_script_generator(cfg.ollama_model)
    script = generate_script(topic, generator, cfg)
    script["script_id"] = f"spike-{topic['id']}"

    logger.info("Script: {}", json.dumps({k: script[k] for k in ("title", "shots")}, indent=2))

    out = _generate_clip(
        script,
        cfg,
        repo,
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"),
        dry_run=args.dry_run,
    )
    if out:
        logger.info("Spike clip: {}", out)
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
