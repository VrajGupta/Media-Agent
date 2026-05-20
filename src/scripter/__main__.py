"""CLI: python -m src.scripter [--dry-run] [--stage a|b|c|all]

Runs scripter stages against the real DB using Ollama qwen2.5:3b-instruct.

Stage A: score + categorise unscripted topics, pick top candidate_pool_size
Stage B: generate scripts for Stage A output
Stage C: score scripts, pick top weekly_clip_target
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config_loader import load_config
from src.state import Repository, connect, initialize_schema
from src.scripter.runner import run_stage_a, run_stage_b, run_stage_c
from src.scripter.ollama_fns import (
    make_topic_scorer, make_topic_tagger,
    make_script_generator, make_script_scorer,
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="src.scripter")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--stage", choices=["a", "b", "c", "all"], default="all")
    parser.add_argument("--dry-run", action="store_true",
                        help="run pipeline but skip DB writes")
    args = parser.parse_args()

    cfg = load_config(args.config)
    model = cfg.ollama_model
    db_path = cfg.abs_path(cfg.paths.state_db)
    conn = connect(db_path)
    initialize_schema(conn)
    repo = Repository(conn)

    run_a = args.stage in ("a", "all")
    run_b = args.stage in ("b", "all")
    run_c = args.stage in ("c", "all")

    selected_topics = []
    scripts = []
    final_scripts = []

    if run_a:
        print(f"[Stage A] scoring + categorising unscripted topics via {model}...")
        selected_topics = run_stage_a(
            cfg, repo,
            scorer_fn=None if args.dry_run else make_topic_scorer(model),
            tagger_fn=None if args.dry_run else make_topic_tagger(model),
        )
        print(f"[Stage A] selected {len(selected_topics)} topic(s)")
        for t in selected_topics:
            score = t.get("weighted_score")
            cat = t.get("category", "?")
            score_str = f"{score:.2f}" if score is not None else "unscored"
            print(f"  [{cat}] {t['title']}  (score={score_str})")

    if run_b and selected_topics:
        print(f"\n[Stage B] generating scripts via {model}...")
        scripts = run_stage_b(
            cfg, repo, selected_topics,
            generator_fn=None if args.dry_run else make_script_generator(model),
        )
        print(f"[Stage B] generated {len(scripts)} script(s)")
        for s in scripts:
            print(f"  [{s.get('script_id','?')[:8]}] {s['title']}")
            print(f"    narration: {s['narration'][:80]}...")
    elif run_b and not selected_topics:
        print("[Stage B] no topics from Stage A — skipping")

    if run_c and scripts:
        print(f"\n[Stage C] scoring scripts via {model}...")
        final_scripts = run_stage_c(
            cfg, repo, scripts,
            scorer_fn=None if args.dry_run else make_script_scorer(model),
        )
        print(f"[Stage C] {len(final_scripts)} script(s) selected for production")
        for s in final_scripts:
            q = s.get("quality_score")
            q_str = f"{q:.2f}" if q is not None else "unscored"
            print(f"  [{s.get('script_id','?')[:8]}] {s['title']}  (quality={q_str})")
            print(f"    narration: {s['narration']}")
            print()
    elif run_c and not scripts:
        print("[Stage C] no scripts from Stage B — skipping")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
