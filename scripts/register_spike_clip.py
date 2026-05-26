"""Register live spike clip in DB and run quality + slot stages."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config_loader import load_config
from src.gen_run import _persist_rendered_clip
from src import quality_screen, slot_planner
from src.state import Repository, connect


def main() -> int:
    cfg = load_config("config.yaml")
    conn = connect(cfg.abs_path(cfg.paths.state_db))
    repo = Repository(conn)

    clip_path = Path("output/pending/__unscheduled__spike-82__it_s_in_the_air_apple_tv_1391.mp4")
    if not clip_path.exists():
        print(f"Missing spike clip: {clip_path}")
        return 1

    script = {
        "script_id": "spike-82",
        "title": "It's in the Air: Apple TV",
        "narration": (
            "Apple TV hits the airwaves with a new streaming bundle. "
            "OnlyFans joins the party. What does this mean for creators?"
        ),
        "shots": [
            {"kind": "real_image", "entity": "apple_tv_logo", "duration_s": 4},
            {"kind": "ai_video", "prompt": "Abstract lights", "duration_s": 4},
            {"kind": "real_image", "entity": "onlyfans_icon", "duration_s": 4},
            {"kind": "ai_video", "prompt": "Soft shadows", "duration_s": 4},
        ],
    }
    _persist_rendered_clip(repo, script, clip_path, duration_s=15.25)
    conn.commit()
    print("persisted clip spike-82")

    qs = quality_screen.run_all(repo, cfg, dry_run=False)
    print("quality_screen:", qs)
    sp = slot_planner.run_all(repo, cfg, dry_run=False)
    print("slot_planner:", sp)

    row = conn.execute(
        "SELECT clip_id, status, output_path, publish_at_utc FROM clips WHERE clip_id=?",
        ("spike-82",),
    ).fetchone()
    print("clip row:", dict(row) if row else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
