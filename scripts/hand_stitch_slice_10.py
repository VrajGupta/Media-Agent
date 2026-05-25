"""Slice 10 one-off: hand-stitch Corti candidate into output/pending/.

DEPRECATED 2026-05-24: superseded by render_from_script.py --reuse-shots/--order.
Use instead:
    python scripts/render_from_script.py \\
        --script-id 7cb41305-b39b-4cc2-855b-067e03549d25 \\
        --reuse-shots data/ai_gen_shots/spike_2026-05-21 \\
        --order 3,2,1,0
    python scripts/insert_ai_gen_clip.py \\
        --script-id 7cb41305-b39b-4cc2-855b-067e03549d25 \\
        --output-path output/pending/__unscheduled__<clip_id>__*.mp4

Reuses the 4 existing Kling shots from data/ai_gen_shots/spike_2026-05-21/.
No new Kling API calls. Shot order [1, 0, 2, 3] so the whiteboard frame
(original shot 1) becomes the auto-thumbnail instead of the synthetic-CEO
frame (original shot 0 — see CONTEXT/phase-review.md for explanation).

Produces:
  output/pending/__unscheduled__<clip_id>__<slug>.mp4
  + a clips row at status='quality_pass', content_kind='ai_generated'

Idempotent: re-running overwrites the MP4 and updates the clips row.

THROWAWAY: delete this script after Slice 10 ships.

Usage:
    python scripts/hand_stitch_slice_10.py [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.assembler.build import build_assembler_argv, write_concat_list
from src.editor.ffmpeg_runner import FfmpegResult, ffprobe_duration_seconds, run_ffmpeg
from src.editor.music import SUPPORTED_EXTENSIONS
from src.editor.slug import title_slug
from src.narration.aligner import align
from src.narration.synth import synthesize
from src.scripter.sanitize import clean_mojibake
from src.state import Repository, connect
from src.subtitles.line_ass import write_line_ass_file

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_ID = "7cb41305-b39b-4cc2-855b-067e03549d25"
SHOT_ORDER = [1, 0, 2, 3]  # swap 0↔1 so whiteboard frame is first

DB_PATH    = ROOT / "data" / "state.db"
SHOTS_DIR  = ROOT / "data" / "ai_gen_shots" / "spike_2026-05-21"
NAR_DIR    = ROOT / "data" / "narration"
SUBS_DIR   = ROOT / "data" / "subtitles"
PENDING    = ROOT / "output" / "pending"
MUSIC_DIR  = ROOT / "data" / "music"

# Stable clip_id derived from SCRIPT_ID so re-runs are idempotent.
CLIP_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, f"slice10:{SCRIPT_ID}"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _shot_path(index: int) -> Path:
    """Return the path for one of the 4 original spike shots (no zero-padding)."""
    return SHOTS_DIR / f"{SCRIPT_ID[:8]}_shot_{index}.mp4"


def _pick_music() -> Path | None:
    """Deterministic music selection via sha1(clip_id) % len(tracks)."""
    if not MUSIC_DIR.exists():
        return None
    tracks = sorted(
        f for f in MUSIC_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    if not tracks:
        return None
    digest = hashlib.sha1(CLIP_ID.encode()).digest()
    idx = int.from_bytes(digest[:8], "big") % len(tracks)
    return tracks[idx]


def _total_duration(shot_paths: list[Path]) -> float:
    """Sum ffprobe durations. Falls back to 5.0 s/shot on probe failure."""
    total = 0.0
    for p in shot_paths:
        d = ffprobe_duration_seconds(p)
        total += d if d is not None else 5.0
    return total


def _hook(narration: str) -> str:
    """First 5 words of narration as the hook field."""
    words = narration.split()
    return " ".join(words[:5])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(dry_run: bool = False) -> None:
    for d in (NAR_DIR, SUBS_DIR, PENDING):
        d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 0. Read script row from DB
    # ------------------------------------------------------------------
    conn = connect(DB_PATH)
    repo = Repository(conn)

    script_row = repo.get_script(SCRIPT_ID)
    if script_row is None:
        print(f"ERROR: script {SCRIPT_ID} not found in {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    raw_narration: str = script_row["narration"]
    narration = clean_mojibake(raw_narration)
    title: str = script_row["title"]
    slug = title_slug(title, CLIP_ID)

    print(f"\n=== hand_stitch_slice_10.py ===")
    print(f"script_id : {SCRIPT_ID}")
    print(f"clip_id   : {CLIP_ID}")
    print(f"title     : {title}")
    print(f"narration : {narration}")
    print(f"dry-run   : {dry_run}")
    print()

    # ------------------------------------------------------------------
    # 1. Locate shots in reordered sequence
    # ------------------------------------------------------------------
    shot_paths = [_shot_path(i) for i in SHOT_ORDER]
    missing = [p for p in shot_paths if not p.exists()]
    if missing:
        print("ERROR: missing shot files:", file=sys.stderr)
        for p in missing:
            print(f"  {p}", file=sys.stderr)
        sys.exit(1)

    print("[1/4] Shots located (reordered):")
    for i, p in zip(SHOT_ORDER, shot_paths):
        print(f"  original shot {i} -> {p.name}")

    output_path = PENDING / f"__unscheduled__{CLIP_ID}__{slug}.mp4"

    if dry_run:
        print(f"\n[dry-run] would write: {output_path}")
        print("[dry-run] would insert/update clips row.")
        print("\nDRY-RUN complete. No files written.")
        return

    # ------------------------------------------------------------------
    # 2. Synthesize narration
    # ------------------------------------------------------------------
    print("\n[2/4] Synthesizing narration...")
    narration_mp3 = NAR_DIR / f"{CLIP_ID}_narration.mp3"
    synthesize(narration, narration_mp3)
    size_kb = narration_mp3.stat().st_size // 1024
    print(f"  synthesized: {narration_mp3.name} ({size_kb} KB)")

    # ------------------------------------------------------------------
    # 3. Align narration + write subtitles
    # ------------------------------------------------------------------
    print("\n[3/4] Aligning narration + generating subtitles...")
    ass_path = SUBS_DIR / f"{CLIP_ID}_subs.ass"
    print("  running Whisper forced-align (large-v3, CUDA)...")
    word_timings = align(narration_mp3)
    write_line_ass_file(ass_path, word_timings)
    print(f"  subtitles: {ass_path.name} ({len(word_timings)} words)")

    # ------------------------------------------------------------------
    # 4. Assemble
    # ------------------------------------------------------------------
    print("\n[4/4] Assembling...")
    total_duration_s = _total_duration(shot_paths)
    music_path = _pick_music()

    if music_path:
        print(f"  music: {music_path.name}")
    else:
        print("  music: none (add YT Audio Library tracks to data/music/)")

    tmp_output = output_path.with_suffix(".tmp.mp4")

    with tempfile.TemporaryDirectory(prefix=f"stitch_{CLIP_ID[:8]}_") as tmpdir:
        concat_list = Path(tmpdir) / "concat.txt"
        write_concat_list(shot_paths, concat_list)

        argv = build_assembler_argv(
            concat_list,
            narration_mp3,
            tmp_output,
            total_duration_s=total_duration_s,
            music_path=music_path,
            ass_path=ass_path,
        )

        result = run_ffmpeg(argv, tmp_output)

    if result.returncode != 0 or result.output_size_bytes == 0:
        if tmp_output.exists():
            tmp_output.unlink()
        print(f"\nERROR: ffmpeg failed (rc={result.returncode})", file=sys.stderr)
        if result.stderr:
            print(result.stderr[-800:], file=sys.stderr)
        sys.exit(1)

    os.replace(tmp_output, output_path)
    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"  assembled: {output_path.name} ({size_mb:.1f} MB)")

    # ------------------------------------------------------------------
    # 5. Insert / update clips row
    # ------------------------------------------------------------------
    print("\n[5/5] Writing clips row...")
    assembled_duration = ffprobe_duration_seconds(output_path) or total_duration_s

    with repo.tx():
        repo.insert_clip(
            clip_id=CLIP_ID,
            video_id=None,
            start_s=0.0,
            end_s=assembled_duration,
            hook=_hook(narration),
            suggested_title=title,
            title_slug=slug,
            selection_method="hand_stitch_slice_10",
            content_kind="ai_generated",
            script_id=SCRIPT_ID,
            status="quality_pass",
            output_path=str(output_path),
        )

    print(f"  clip_id   : {CLIP_ID}")
    print(f"  status    : quality_pass")
    print(f"  output    : {output_path.name}")

    print(f"\nDone. Review the clip:")
    print(f"  {output_path}")
    print(f"\nThen drag it to output/approved/ and run:")
    print(f"  python -m src.daily_upload --dry-run   # review upload JSON first")
    print(f"  python -m src.daily_upload              # live upload")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hand-stitch Slice 10 Corti candidate.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
