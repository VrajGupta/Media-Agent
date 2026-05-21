"""Slice 4 tracer bullet — hand-script -> one watchable MP4.

Takes a hand-written {title, narration, shots[]} JSON and wires:
  ai_gen (OpenRouter Kling) -> narration (Edge TTS) -> assembler (ffmpeg)

Usage:
    python scripts/render_from_script.py --script scripts/sample_script.json
    python scripts/render_from_script.py --script scripts/sample_script.json --dry-run

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
from src.editor.ffmpeg_runner import FfmpegResult, run_ffmpeg
from src.editor.music import SUPPORTED_EXTENSIONS
from src.editor.slug import title_slug
from src.narration.synth import synthesize

STYLE_SUFFIX = (
    "clean editorial product photography, soft studio lighting, "
    "neutral backgrounds, minimalist composition, sharp focus, "
    "vertical 9:16, premium tech magazine look"
)

PENDING_DIR = ROOT / "output" / "pending"
SHOTS_DIR = ROOT / "data" / "ai_gen_shots" / "render_tracer"
NARRATION_DIR = ROOT / "data" / "narration"
MUSIC_DIR = ROOT / "data" / "music"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_script(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = {"title", "narration", "shots"}
    missing = required - set(raw)
    if missing:
        raise ValueError(f"script JSON missing keys: {missing}")
    if not raw["shots"]:
        raise ValueError("shots list is empty")
    return raw


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
    parser.add_argument("--script", required=True, type=Path, help="Path to script JSON file")
    parser.add_argument("--dry-run", action="store_true", help="Skip all API calls and ffmpeg")
    args = parser.parse_args()

    script = _load_script(args.script)
    title = script["title"]
    narration_text = script["narration"]
    shots_raw = _apply_style_suffix(script["shots"])

    clip_id = str(uuid.uuid4())[:8]
    slug = title_slug(title, clip_id)

    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    NARRATION_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n=== render_from_script.py ===")
    print(f"title    : {title}")
    print(f"clip_id  : {clip_id}")
    print(f"shots    : {len(shots_raw)}")
    print(f"dry-run  : {args.dry_run}")
    print()

    # ------------------------------------------------------------------
    # Stage 1 — Generate shots
    # ------------------------------------------------------------------
    print("[1/3] Generating shots...")

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
    print("\n[2/3] Synthesizing narration...")

    narration_mp3 = NARRATION_DIR / f"{clip_id}_narration.mp3"

    if args.dry_run:
        narration_mp3.write_bytes(b"PLACEHOLDER-MP3")
        print(f"  [dry-run] placeholder: {narration_mp3.name}")
    else:
        synthesize(narration_text, narration_mp3)
        size_kb = narration_mp3.stat().st_size // 1024
        print(f"  synthesized: {narration_mp3.name} ({size_kb} KB)")

    # ------------------------------------------------------------------
    # Stage 3 — Assemble
    # ------------------------------------------------------------------
    print("\n[3/3] Assembling...")

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

        # Estimate total duration from shot durations (fallback: 5s/shot)
        total_duration_s = sum(s.get("duration_s", 5) for s in shots_raw)

        tmp_output = output_path.with_suffix(".tmp.mp4")
        argv = build_assembler_argv(
            concat_list,
            narration_mp3,
            tmp_output,
            total_duration_s=float(total_duration_s),
            music_path=music_path,
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
