"""Throwaway end-to-end hybrid spike (Pivot.7 / P7.6).

One real topic → tagged shots → hybrid routing → Kokoro → assemble → output/pending/.
Operator validates visuals, voice, and cost manually.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config_loader import load_config
from src.gen_run import _generate_clip
from src.image_fetch.fetcher import provenance_for_entity
from src.observability import setup_logging
from src.scripter.ollama_fns import make_script_generator
from src.scripter.runner import generate_script
from src.scripter.shot_plan import normalize_shots
from src.state import Repository, connect

PIVOT6_4SHOT_BASELINE_CENTS = 134


def _print_provenance_report(script: dict, cfg) -> None:
    print("\n=== Provenance report (real_image shots) ===")
    for i, shot in enumerate(normalize_shots(script.get("shots", []))):
        if shot.get("kind") != "real_image":
            continue
        entity = shot["entity"]
        query = shot.get("search_query")
        asset = provenance_for_entity(entity, query, cfg)
        if asset is None:
            print(f"  shot {i}: {entity!r} — no cached sidecar (fetch may have failed or cache cleared)")
            continue
        print(
            f"  shot {i}: {entity!r}\n"
            f"    source={asset.source!r} license={asset.license!r}\n"
            f"    url={asset.source_url}"
        )


def _print_cost_report(repo: Repository, clip_cost_cents: int) -> None:
    today_total = repo.quota_today_total(provider="openrouter")
    half_baseline = PIVOT6_4SHOT_BASELINE_CENTS // 2
    print("\n=== Cost report (OpenRouter / Kling) ===")
    print(f"  this clip: {clip_cost_cents}c (${clip_cost_cents / 100:.2f})")
    print(f"  today total (openrouter): {today_total}c (${today_total / 100:.2f})")
    print(
        f"  vs Pivot.6 4-shot baseline ({PIVOT6_4SHOT_BASELINE_CENTS}c): "
        f"{clip_cost_cents / PIVOT6_4SHOT_BASELINE_CENTS * 100:.0f}% "
        f"(expect ~50% / ~{half_baseline}c for 2 ai_video shots)"
    )
    print("  reconcile ±10% against OpenRouter dashboard before HITL sign-off")


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

    openrouter_before = repo.quota_today_total(provider="openrouter")
    out = _generate_clip(
        script,
        cfg,
        repo,
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"),
        dry_run=args.dry_run,
    )
    clip_cost = repo.quota_today_total(provider="openrouter") - openrouter_before

    if out:
        logger.info("Spike clip: {}", out)
        print(out)
        _print_provenance_report(script, cfg)
        _print_cost_report(repo, clip_cost)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
