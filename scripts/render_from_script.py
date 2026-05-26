"""Slice 4/5 tracer bullet — hand-script -> one watchable MP4 with subtitles.

Takes a hand-written {title, narration, shots[]} JSON and wires:
  ai_gen (OpenRouter Kling) -> narration (Edge TTS) -> Whisper align -> line ASS -> assembler (ffmpeg)

Usage:
    python scripts/render_from_script.py --script scripts/sample_script.json
    python scripts/render_from_script.py --script scripts/sample_script.json --dry-run

    # Slice 10 — reuse existing Kling shots (skips Stage-1 generation, no OpenRouter):
    python scripts/render_from_script.py \\
        --script-id 7cb41305-b39b-4cc2-855b-067e03549d25 \\
        --reuse-shots data/ai_gen_shots/spike_2026-05-21 \\
        --order 3,2,1,0

    --dry-run: skips all API calls and ffmpeg; prints what would happen.

Input JSON format:
    {
        "title": "The AI That Rewrites Itself",
        "narration": "~40 words for voiceover",
        "shots": [
            {"prompt": "visual description of shot", "duration_s": 5},
            ...
        ]
    }

Output:
    output/pending/__unscheduled__{clip_id}__{slug}.mp4
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from dotenv import load_dotenv

# Ensure project root is importable.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from src.ai_gen.openrouter_kling import OpenRouterKlingClient
from src.ai_gen.runner import generate_shots
from src.assembler.build import build_assembler_argv, write_concat_list
from src.editor.ffmpeg_runner import ffprobe_duration_seconds, run_ffmpeg
from src.editor.music import SUPPORTED_EXTENSIONS
from src.editor.slug import title_slug
from src.narration.aligner import align
from src.narration.synth import synthesize
from src.config_loader import load_config
from src.state import Repository, connect
from src.subtitles.line_ass import write_line_ass_file

STYLE_SUFFIX = (
    "clean editorial product photography, soft studio lighting, "
    "neutral backgrounds, minimalist composition, sharp focus, "
    "vertical 9:16, premium tech magazine look"
)

PENDING_DIR = ROOT / "output" / "pending"
SHOTS_DIR = ROOT / "data" / "ai_gen_shots" / "render_tracer"
NARRATION_DIR = ROOT / "data" / "narration"
SUBS_DIR = ROOT / "data" / "subtitles"
MUSIC_DIR = ROOT / "data" / "music"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_shot_order(order_str: str, *, expected_count: int | None = None) -> list[int]:
    """Parse a comma-separated shot index list, e.g. ``3,2,1,0``."""
    parts = [p.strip() for p in order_str.split(",") if p.strip()]
    if not parts:
        raise ValueError("order must list at least one shot index")
    try:
        order = [int(p) for p in parts]
    except ValueError as exc:
        raise ValueError(f"order must be comma-separated integers: {order_str!r}") from exc
    if expected_count is not None and len(order) != expected_count:
        raise ValueError(f"order must contain exactly {expected_count} indices, got {len(order)}")
    return order


def resolve_reused_shot_paths(
    shots_dir: Path,
    script_id: str,
    order: list[int],
) -> list[Path]:
    """Return existing shot MP4 paths in play order. Raises if any file is missing."""
    prefix = script_id[:8]
    paths = [shots_dir / f"{prefix}_shot_{i}.mp4" for i in order]
    missing = [p for p in paths if not p.exists()]
    if missing:
        names = ", ".join(p.name for p in missing)
        raise FileNotFoundError(f"missing reused shot files: {names}")
    return paths


def stable_clip_id(script_id: str) -> str:
    """Deterministic clip_id for idempotent re-runs from the same script."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"render:{script_id}"))


def _load_script(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = {"title", "narration", "shots"}
    missing = required - set(raw)
    if missing:
        raise ValueError(f"script JSON missing keys: {missing}")
    if not raw["shots"]:
        raise ValueError("shots list is empty")
    return raw


def _load_script_from_db(db_path: Path, script_id: str) -> dict:
    conn = connect(db_path)
    try:
        repo = Repository(conn)
        row = repo.get_script(script_id)
        if row is None:
            raise ValueError(f"script {script_id!r} not found in {db_path}")
        return {
            "script_id": row["script_id"],
            "title": row["title"],
            "narration": clean_mojibake(row["narration"]),
            "shots": json.loads(row["shots_json"]),
        }
    finally:
        conn.close()


def _total_shot_duration(shot_paths: list[Path]) -> float:
    total = 0.0
    for path in shot_paths:
        duration = ffprobe_duration_seconds(path)
        total += duration if duration is not None else 5.0
    return total


def _apply_style_suffix(shots: list[dict]) -> list[dict]:
    return [
        {**s, "prompt": f"{s['prompt']}, {STYLE_SUFFIX}"}
        for s in shots
    ]


def _pick_music() -> Path | None:
    if not MUSIC_DIR.exists():
        return None
    tracks = sorted(
        f for f in MUSIC_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    return tracks[0] if tracks else None


def _placeholder_mp4(path: Path) -> None:
    """Write a minimal valid-ish placeholder mp4 for dry-run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Actually create a 1-second silent video via ffmpeg if available.
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        subprocess.run(
            [
                ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=black:s=1080x1920:r=30:d=1",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                "-t", "1",
                "-c:v", "libx264", "-c:a", "aac",
                str(path),
            ],
            check=False,
        )
    else:
        path.write_bytes(b"PLACEHOLDER-MP4")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Render one AI-generated Short from a script JSON.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--script", type=Path, help="Path to script JSON file")
    src.add_argument(
        "--script-id",
        help="Load script row from data/state.db (requires --reuse-shots)",
    )
    parser.add_argument(
        "--reuse-shots",
        type=Path,
        help="Directory of existing shot MP4s; skips Stage-1 Kling generation",
    )
    parser.add_argument(
        "--order",
        help="Comma-separated original shot indices in play order, e.g. 3,2,1,0",
    )
    parser.add_argument("--dry-run", action="store_true", help="Skip all API calls and ffmpeg")
    args = parser.parse_args()

    if args.script_id and not args.reuse_shots:
        parser.error("--script-id requires --reuse-shots (no regeneration)")
    if args.reuse_shots and not args.order:
        parser.error("--reuse-shots requires --order")
    if args.script:
        script = _load_script(args.script)
        clip_id = str(uuid.uuid4())[:8]
    else:
        script = _load_script_from_db(ROOT / "data" / "state.db", args.script_id)
        clip_id = stable_clip_id(script["script_id"])

    title = script["title"]
    narration_text = script["narration"]
    shots_raw = script["shots"]
    if not args.reuse_shots:
        shots_raw = _apply_style_suffix(shots_raw)

    slug = title_slug(title, clip_id)
    shot_order = parse_shot_order(args.order, expected_count=4) if args.order else None

    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    NARRATION_DIR.mkdir(parents=True, exist_ok=True)
    SUBS_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n=== render_from_script.py ===")
    print(f"title    : {title}")
    print(f"clip_id  : {clip_id}")
    print(f"shots    : {len(shots_raw)}")
    print(f"dry-run  : {args.dry_run}")
    if args.reuse_shots:
        print(f"reuse    : {args.reuse_shots}")
        print(f"order    : {shot_order}")
    print()

    ass_path = SUBS_DIR / f"{clip_id}_subs.ass"

    # ------------------------------------------------------------------
    # Stage 1 — Generate shots (skipped when --reuse-shots is set)
    # ------------------------------------------------------------------
    if args.reuse_shots:
        print("[1/4] Reusing existing shots (no OpenRouter call)...")
        if args.dry_run:
            prefix = script.get("script_id", clip_id)[:8]
            shot_paths = [args.reuse_shots / f"{prefix}_shot_{i}.mp4" for i in shot_order]
            for i, p in zip(shot_order, shot_paths):
                print(f"  [dry-run] would use original shot {i}: {p.name}")
        else:
            shot_paths = resolve_reused_shot_paths(
                args.reuse_shots,
                script["script_id"],
                shot_order,
            )
            for i, p in zip(shot_order, shot_paths):
                print(f"  original shot {i} -> {p.name}")
    else:
        print("[1/4] Generating shots...")

        if args.dry_run:
            shot_paths: list[Path] = []
            for i, s in enumerate(shots_raw):
                p = SHOTS_DIR / f"{clip_id}_shot_{i:02d}.mp4"
                _placeholder_mp4(p)
                shot_paths.append(p)
                print(f"  [dry-run] placeholder: {p.name}")
        else:
            api_key = os.environ.get("OPENROUTER_API_KEY")
            if not api_key:
                sys.exit("ERROR: OPENROUTER_API_KEY not set")
            client = OpenRouterKlingClient(api_key=api_key)
            shot_paths = generate_shots(shots_raw, SHOTS_DIR, client)
            for p in shot_paths:
                print(f"  downloaded: {p.name}")

    # ------------------------------------------------------------------
    # Stage 2 — Synthesize narration
    # ------------------------------------------------------------------
    print("\n[2/4] Synthesizing narration...")

    narration_mp3 = NARRATION_DIR / f"{clip_id}_narration.mp3"

    if args.dry_run:
        narration_mp3.write_bytes(b"PLACEHOLDER-MP3")
        print(f"  [dry-run] placeholder: {narration_mp3.name}")
    else:
        synthesize(narration_text, narration_mp3)
        size_kb = narration_mp3.stat().st_size // 1024
        print(f"  synthesized: {narration_mp3.name} ({size_kb} KB)")

    # ------------------------------------------------------------------
    # Stage 3 — Align narration + write subtitles
    # ------------------------------------------------------------------
    print("\n[3/4] Aligning narration + generating subtitles...")

    if args.dry_run:
        write_line_ass_file(ass_path, [])
        print(f"  [dry-run] placeholder ASS: {ass_path.name}")
    else:
        print("  running Whisper forced-align (large-v3, CUDA)...")
        word_timings = align(narration_mp3)
        write_line_ass_file(ass_path, word_timings)
        print(f"  subtitles: {ass_path.name} ({len(word_timings)} words)")

    # ------------------------------------------------------------------
    # Stage 4 — Assemble
    # ------------------------------------------------------------------
    print("\n[4/4] Assembling...")

    output_path = PENDING_DIR / f"__unscheduled__{clip_id}__{slug}.mp4"
    music_path = _pick_music()

    if music_path:
        print(f"  music: {music_path.name}")
    else:
        print("  music: none (drop mp3/m4a into data/music/ to enable)")

    if args.dry_run:
        print(f"  [dry-run] would write: {output_path}")
        print("\nDRY-RUN complete. No files assembled.")
        return

    with tempfile.TemporaryDirectory(prefix=f"render_{clip_id}_") as tmpdir:
        concat_list = Path(tmpdir) / "concat.txt"
        write_concat_list(shot_paths, concat_list)

        cfg = load_config(ROOT / "config.yaml")
        asm_cfg = cfg.assembler

        if args.reuse_shots:
            durations = [ffprobe_duration_seconds(p) or 5.0 for p in shot_paths]
        else:
            durations = [float(s.get("duration_s", 5)) for s in shots_raw]

        if asm_cfg.crossfade_enabled and len(shot_paths) > 1:
            total_duration_s = sum(durations) - asm_cfg.crossfade_duration_s * (len(durations) - 1)
        else:
            total_duration_s = sum(durations)

        tmp_output = output_path.with_suffix(".tmp.mp4")
        multi_shot = len(shot_paths) > 1
        argv = build_assembler_argv(
            concat_list,
            narration_mp3,
            tmp_output,
            total_duration_s=float(total_duration_s),
            music_path=music_path,
            ass_path=ass_path,
            music_volume_db=float(cfg.music_volume_db),
            loudness_target_lufs=float(cfg.loudness_target_lufs),
            nvenc_preset=cfg.nvenc_preset,
            nvenc_cq=int(cfg.nvenc_cq),
            shot_paths=shot_paths if multi_shot else None,
            crossfade_enabled=asm_cfg.crossfade_enabled,
            crossfade_duration_s=float(asm_cfg.crossfade_duration_s),
            shot_durations_s=durations if multi_shot and asm_cfg.crossfade_enabled else None,
            resolution=tuple(cfg.output_resolution),
            fps=int(cfg.output_fps),
        )

        result = run_ffmpeg(argv, tmp_output)

    if result.returncode != 0 or result.output_size_bytes == 0:
        if tmp_output.exists():
            tmp_output.unlink()
        print(f"\nERROR: ffmpeg failed (rc={result.returncode})")
        if result.stderr:
            print(result.stderr[-500:])
        sys.exit(1)

    import os as _os
    _os.replace(tmp_output, output_path)
    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"  assembled: {output_path.name} ({size_mb:.1f} MB)")

    print(f"\nDone. Open to review:")
    print(f"  {output_path}")


if __name__ == "__main__":
    main()
