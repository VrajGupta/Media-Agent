"""Insert or update an ai_generated clips row after render_from_script.

Usage:
    python scripts/insert_ai_gen_clip.py \\
        --script-id 7cb41305-b39b-4cc2-855b-067e03549d25 \\
        --output-path output/pending/__unscheduled__<clip_id>__corti-symphony.mp4 \\
        [--duration-s 16.0]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.editor.ffmpeg_runner import ffprobe_duration_seconds
from src.editor.slug import title_slug
from src.scripter.sanitize import clean_mojibake
from src.state import Repository, connect

from scripts.render_from_script import stable_clip_id

DB_PATH = ROOT / "data" / "state.db"


def hook_from_narration(narration: str) -> str:
    return " ".join(narration.split()[:5])


def upsert_ai_gen_clip(
    repo: Repository,
    *,
    script_id: str,
    output_path: Path | str,
    duration_s: float,
    title: str,
    narration: str,
    selection_method: str = "render_from_script",
) -> str:
    clip_id = stable_clip_id(script_id)
    slug = title_slug(title, clip_id)
    repo.insert_clip(
        clip_id=clip_id,
        video_id=None,
        start_s=0.0,
        end_s=float(duration_s),
        hook=hook_from_narration(narration),
        suggested_title=title,
        title_slug=slug,
        selection_method=selection_method,
        content_kind="ai_generated",
        script_id=script_id,
        status="quality_pass",
        output_path=str(output_path),
    )
    return clip_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Insert/update ai_generated clips row.")
    parser.add_argument("--script-id", required=True)
    parser.add_argument("--output-path", required=True, type=Path)
    parser.add_argument(
        "--duration-s",
        type=float,
        help="Clip duration in seconds (defaults to ffprobe on output-path)",
    )
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()

    if not args.output_path.exists():
        print(f"ERROR: output file not found: {args.output_path}", file=sys.stderr)
        sys.exit(1)

    duration_s = args.duration_s
    if duration_s is None:
        duration_s = ffprobe_duration_seconds(args.output_path)
    if duration_s is None:
        print("ERROR: could not determine duration; pass --duration-s", file=sys.stderr)
        sys.exit(1)

    conn = connect(args.db)
    repo = Repository(conn)
    try:
        script_row = repo.get_script(args.script_id)
        if script_row is None:
            print(f"ERROR: script {args.script_id!r} not found", file=sys.stderr)
            sys.exit(1)

        narration = clean_mojibake(script_row["narration"])
        clip_id = upsert_ai_gen_clip(
            repo,
            script_id=args.script_id,
            output_path=args.output_path,
            duration_s=duration_s,
            title=script_row["title"],
            narration=narration,
        )
        conn.commit()
    finally:
        conn.close()

    print(f"clip_id     : {clip_id}")
    print(f"status      : quality_pass")
    print(f"output_path : {args.output_path}")


if __name__ == "__main__":
    main()
