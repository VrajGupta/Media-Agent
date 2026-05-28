"""Render one pending script from DB to output/pending/ (skip ingest/scripter)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.config_loader import load_config
from src.gen_run import _generate_clip, _persist_rendered_clip, _script_dict_from_row
from src.observability.logging_setup import setup_logging
from src.scripter.shots import normalize_shots
from src.scripter.shot_plan import resolve_shot_plan
from src.image_fetch.fetcher import probe_licensed_image
from src.state import Repository, connect

SCRIPT_ID = "05bed0bd-2026-4442-aedb-59dff837a184"


def main() -> int:
    cfg = load_config(ROOT / "config.yaml")
    setup_logging(cfg.abs_path(cfg.paths.logs_dir))
    conn = connect(cfg.abs_path(cfg.paths.state_db))
    repo = Repository(conn)
    row = conn.execute(
        "SELECT * FROM scripts WHERE script_id = ?", (SCRIPT_ID,)
    ).fetchone()
    if not row:
        print(f"script not found: {SCRIPT_ID}")
        return 1
    script = _script_dict_from_row(row)
    normalized = normalize_shots(script["shots"])
    resolved, billable = resolve_shot_plan(
        normalized,
        licensed_probe=lambda entity, query: probe_licensed_image(entity, query, cfg),
    )
    print(f"Rendering {script['title']!r} — {billable} billable ai_video shots")
    out = _generate_clip(
        script,
        cfg,
        repo,
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"),
        dry_run=False,
    )
    if not out:
        print("generate returned None")
        return 1
    durations = [float(s.get("duration_s", 4)) for s in resolved]
    asm = cfg.assembler
    if asm.crossfade_enabled and len(durations) > 1:
        duration_s = sum(durations) - asm.crossfade_duration_s * (len(durations) - 1)
    else:
        duration_s = sum(durations)
    _persist_rendered_clip(repo, script, out, duration_s=duration_s)
    conn.commit()
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
