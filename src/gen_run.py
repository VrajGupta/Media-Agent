"""Pivot.6 weekly generation orchestrator.

Replaces weekly_run.py for the AI-generated pipeline:
  topic_ingest → scripter A/B/C → policy_gate
  → per-script: ai_gen + narration + assemble
  → quality_screen → slot_planner → retention

Usage:
    python -m src.gen_run [--dry-run] [--clips N] [--config config.yaml]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from src.config_loader import Config, load_config
from src.observability import (
    RunLockHeld, acquire_run_lock, append_alert, append_run_row, setup_logging,
)
from src.state import Repository, connect

# Stage imports — imported into this namespace so tests can patch at src.gen_run.*
from src.topic_ingest.runner import fetch_unscripted_topics
from src.scripter.runner import run_stage_a, run_stage_b, run_stage_c

from src import policy_gate, quality_screen, slot_planner, retention

# Per-clip stage imports at module level so tests can patch src.gen_run.*
from src.ai_gen.openrouter_kling import OpenRouterKlingClient
from src.ai_gen.runner import generate_shots
from src.assembler.build import build_assembler_argv, write_concat_list
from src.assembler.ken_burns import build_ken_burns_argv
from src.editor.ffmpeg_runner import run_ffmpeg
from src.editor.music import SUPPORTED_EXTENSIONS
from src.editor.slug import title_slug
from src.image_fetch.fetcher import fetch_image
from src.image_fetch.errors import ImageFetchError
from src.narration.aligner import align
from src.narration.synth import synthesize
from src.scripter.shots import normalize_shots
from src.subtitles.line_ass import write_line_ass_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _summarize(results: Any) -> Any:
    if results is None:
        return None
    if isinstance(results, list):
        return {"count": len(results)}
    if hasattr(results, "__dict__"):
        return {k: v for k, v in vars(results).items() if not k.startswith("_")}
    return {"value": str(results)[:120]}


def _build_runs_md_summary(summary: dict) -> str:
    stages = summary.get("stages") or {}
    bits = []
    for name, s in stages.items():
        if isinstance(s, dict) and "count" in s:
            bits.append(f"{name}={s['count']}")
        else:
            bits.append(name)
    base = "stages={" + ", ".join(bits) + "}"
    if "error" in summary:
        base += f"; error={summary['error']}"
    return base


def count_ai_video_shots(shots: list[dict]) -> int:
    """Count ai_video shots for cost projection."""
    return sum(1 for s in shots if s.get("kind") == "ai_video")


_ENCODER_FAILURE_MARKERS = (
    "h264_nvenc",
    "nvenc",
    "no nvenc capable devices",
    "cannot load nvcuda",
    "error initializing output stream",
    "encoder",
)


def _is_encoder_failure(stderr: str) -> bool:
    lower = stderr.lower()
    return any(marker in lower for marker in _ENCODER_FAILURE_MARKERS)


def _log_assembly_failure(cfg, clip_id: str, result) -> None:
    logs_dir = cfg.abs_path(cfg.paths.logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    tail = (result.stderr or "")[-4000:]
    failure_log = logs_dir / f"assembly_fail_{clip_id}.log"
    failure_log.write_text(tail, encoding="utf-8")
    append_alert(
        logs_dir,
        "assembly_failed",
        f"clip {clip_id}: ffmpeg rc={result.returncode}; see {failure_log.name}",
    )


def _run_assembly(
    *,
    cfg,
    clip_id: str,
    concat_list: Path,
    narration_mp3: Path,
    tmp_output: Path,
    total_duration_s: float,
    music_path: Path | None,
    ass_path: Path,
    shot_paths: list[Path],
    asm_cfg,
    durations: list[float],
    video_codec: str = "h264_nvenc",
):
    resolution = tuple(cfg.output_resolution)
    fps = int(getattr(cfg, "output_fps", 30))
    multi_shot = len(shot_paths) > 1
    return run_ffmpeg(
        build_assembler_argv(
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
            shot_durations_s=durations,
            resolution=resolution,
            fps=fps,
            video_codec=video_codec,
        ),
        tmp_output,
    )


def _render_real_image_shot(
    shot: dict,
    index: int,
    shots_dir: Path,
    cfg,
) -> Path:
    entity = shot["entity"]
    query = shot.get("search_query")
    asset = fetch_image(entity, query, cfg)
    dest = shots_dir / f"shot_{index:02d}.mp4"
    tmp = dest.with_suffix(".tmp.mp4")
    argv = build_ken_burns_argv(
        Path(asset.path),
        tmp,
        duration_s=float(shot.get("duration_s", 4)),
        resolution=tuple(cfg.output_resolution),
        zoom_rate=float(getattr(cfg, "ken_burns_zoom_rate", 0.0015)),
        blurred_bg_sigma=int(getattr(cfg, "blurred_bg_sigma", 20)),
        nvenc_preset=cfg.nvenc_preset,
        nvenc_cq=int(cfg.nvenc_cq),
    )
    result = run_ffmpeg(argv, tmp)
    if result.returncode != 0 or result.output_size_bytes == 0:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"Ken Burns render failed for shot {index}")
    os.replace(tmp, dest)
    return dest


def _generate_clip(
    script: dict,
    cfg,
    repo: Repository,
    *,
    openrouter_api_key: str | None,
    dry_run: bool,
) -> Path | None:
    """Run hybrid shot routing → narration → assemble for one script."""
    clip_id = script.get("script_id", str(uuid.uuid4())[:8])
    title = script.get("title", "untitled")
    narration_text = script.get("narration", "")
    shots_raw = script.get("shots", [])

    ai_cfg = cfg.ai_gen
    narr_cfg = cfg.narration
    asm_cfg = cfg.assembler
    style_suffix = ai_cfg.style_suffix if ai_cfg.style_suffix else ""
    normalized = normalize_shots(shots_raw)

    pending_dir = cfg.abs_path(cfg.paths.pending_dir)
    pending_dir.mkdir(parents=True, exist_ok=True)
    shots_dir = Path(tempfile.mkdtemp(prefix=f"gen_{clip_id}_shots_"))
    narration_dir = Path(tempfile.mkdtemp(prefix=f"gen_{clip_id}_narr_"))
    subs_dir = Path(tempfile.mkdtemp(prefix=f"gen_{clip_id}_subs_"))

    slug = title_slug(title, clip_id)
    output_path = pending_dir / f"__unscheduled__{clip_id}__{slug}.mp4"

    if dry_run:
        logger.info("[dry-run] skipping ai_gen + narration + assemble for {}", clip_id)
        return None

    ai_shots = [
        {
            **s,
            "prompt": f"{s['prompt']}, {style_suffix}".strip(", "),
        }
        for s in normalized
        if s.get("kind") == "ai_video"
    ]
    ai_paths: list[Path] = []
    if ai_shots:
        if not openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY required for ai_video shots")
        client = OpenRouterKlingClient(api_key=openrouter_api_key)
        ai_paths = generate_shots(
            ai_shots, shots_dir, client, max_concurrent=ai_cfg.max_concurrent,
        )

    shot_paths: list[Path] = []
    ai_idx = 0
    for i, shot in enumerate(normalized):
        if shot.get("kind") == "real_image":
            shot_paths.append(_render_real_image_shot(shot, i, shots_dir, cfg))
        else:
            shot_paths.append(ai_paths[ai_idx])
            ai_idx += 1

    narration_mp3 = narration_dir / f"{clip_id}_narration.mp3"
    synthesize(
        narration_text,
        narration_mp3,
        voice=narr_cfg.voice,
        rate=narr_cfg.rate,
        pitch=narr_cfg.pitch,
        engine=narr_cfg.engine,
        kokoro_voice=narr_cfg.kokoro_voice,
    )

    word_timings = align(narration_mp3)
    ass_path = subs_dir / f"{clip_id}_subs.ass"
    write_line_ass_file(ass_path, word_timings)

    with tempfile.TemporaryDirectory(prefix=f"gen_{clip_id}_build_") as tmpdir:
        concat_list = Path(tmpdir) / "concat.txt"
        write_concat_list(shot_paths, concat_list)
        durations = [float(s.get("duration_s", 4)) for s in normalized]
        if asm_cfg.crossfade_enabled and len(shot_paths) > 1:
            total_duration_s = sum(durations) - asm_cfg.crossfade_duration_s * (len(durations) - 1)
        else:
            total_duration_s = sum(durations)
        tmp_output = output_path.with_suffix(".tmp.mp4")

        music_dir = cfg.abs_path("data/music")
        music_path: Path | None = None
        if music_dir.exists():
            tracks = sorted(
                f for f in music_dir.iterdir()
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
            )
            music_path = tracks[0] if tracks else None

        result = _run_assembly(
            cfg=cfg,
            clip_id=clip_id,
            concat_list=concat_list,
            narration_mp3=narration_mp3,
            tmp_output=tmp_output,
            total_duration_s=total_duration_s,
            music_path=music_path,
            ass_path=ass_path,
            shot_paths=shot_paths,
            asm_cfg=asm_cfg,
            durations=durations,
        )

        if result.returncode != 0 or result.output_size_bytes == 0:
            if _is_encoder_failure(result.stderr or ""):
                logger.warning("NVENC assembly failed for {}; retrying with libx264", clip_id)
                result = _run_assembly(
                    cfg=cfg,
                    clip_id=clip_id,
                    concat_list=concat_list,
                    narration_mp3=narration_mp3,
                    tmp_output=tmp_output,
                    total_duration_s=total_duration_s,
                    music_path=music_path,
                    ass_path=ass_path,
                    shot_paths=shot_paths,
                    asm_cfg=asm_cfg,
                    durations=durations,
                    video_codec="libx264",
                )

    if result.returncode != 0 or result.output_size_bytes == 0:
        if tmp_output.exists():
            tmp_output.unlink()
        _log_assembly_failure(cfg, clip_id, result)
        raise RuntimeError(
            f"ffmpeg failed (rc={result.returncode}) for clip {clip_id}"
        )

    os.replace(tmp_output, output_path)
    logger.info("assembled: {}", output_path.name)
    return output_path


# ---------------------------------------------------------------------------
# Core orchestrator
# ---------------------------------------------------------------------------


def run_generation(
    *,
    repo: Repository,
    cfg: Config,
    clips_n: int = 2,
    dry_run: bool = False,
    openrouter_api_key: str | None = None,
    ollama_host: str | None = None,
) -> tuple[bool, dict]:
    """Run the Pivot.6 generation pipeline. Returns (success, summary)."""
    logs_dir = cfg.abs_path(cfg.paths.logs_dir)
    started_at_utc = datetime.now(timezone.utc)
    run_id = repo.start_run(kind="generation")
    summary: dict[str, Any] = {"stages": {}, "dry_run": dry_run}

    try:
        # --- Batch stages: topic ingest + scripting ---
        logger.info("gen_run: stage=topic_ingest")
        topics = fetch_unscripted_topics(cfg, repo, dry_run=dry_run)
        summary["stages"]["topic_ingest"] = _summarize(topics)

        logger.info("gen_run: stage=scripter_a")
        topics_scored = run_stage_a(cfg, repo)
        summary["stages"]["scripter_a"] = _summarize(topics_scored)

        logger.info("gen_run: stage=scripter_b")
        scripts = run_stage_b(cfg, repo, topics_scored)
        summary["stages"]["scripter_b"] = _summarize(scripts)

        logger.info("gen_run: stage=scripter_c")
        selected = run_stage_c(cfg, repo, scripts)[:clips_n]
        summary["stages"]["scripter_c"] = _summarize(selected)

        # --- Per-script: policy gate, then generate clip ---
        logger.info("gen_run: stage=policy_gate")
        gate_results = policy_gate.run_all(
            repo, cfg, dry_run=dry_run, ollama_host=ollama_host,
        )
        summary["stages"]["policy_gate"] = _summarize(gate_results)

        clips_generated = 0
        for script in selected:
            try:
                _generate_clip(
                    script, cfg, repo,
                    openrouter_api_key=openrouter_api_key,
                    dry_run=dry_run,
                )
                clips_generated += 1
            except ImageFetchError as exc:
                logger.error(
                    "gen_run: image fetch failed for {}: {}",
                    script.get("script_id"), exc,
                )
            except Exception as exc:
                logger.error("gen_run: clip generation failed for {}: {}", script.get("script_id"), exc)
        summary["stages"]["generate_clips"] = {"count": clips_generated}

        # --- Batch stages: screen + slot + retain ---
        logger.info("gen_run: stage=quality_screen")
        qs_results = quality_screen.run_all(repo, cfg, dry_run=dry_run)
        summary["stages"]["quality_screen"] = _summarize(qs_results)

        logger.info("gen_run: stage=slot_planner")
        sp_results = slot_planner.run_all(repo, cfg, dry_run=dry_run)
        summary["stages"]["slot_planner"] = _summarize(sp_results)

        logger.info("gen_run: stage=retention")
        ret_results = retention.run_all(repo, cfg, dry_run=dry_run)
        summary["stages"]["retention"] = _summarize(ret_results)

        repo.finish_run(run_id, success=True, summary_json=json.dumps(summary))
        append_alert(
            logs_dir, kind="gen_run_finished",
            message=f"gen_run finished; stages={list(summary['stages'].keys())}",
        )
        append_run_row(
            logs_dir, kind="generation",
            started_at=started_at_utc, finished_at=datetime.now(timezone.utc),
            success=True, summary=_build_runs_md_summary(summary),
        )

    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        repo.finish_run(run_id, success=False, summary_json=json.dumps(summary))
        append_alert(
            logs_dir, kind="gen_run_failed",
            message=summary["error"],
        )
        append_run_row(
            logs_dir, kind="generation",
            started_at=started_at_utc, finished_at=datetime.now(timezone.utc),
            success=False, summary=_build_runs_md_summary(summary),
        )
        raise

    return (True, summary)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(prog="src.gen_run")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--clips", type=int, default=2, dest="clips_n")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    logs_dir = cfg.abs_path(cfg.paths.logs_dir)
    setup_logging(logs_dir)

    db_path = cfg.abs_path(cfg.paths.state_db)
    if not db_path.exists():
        logger.error(f"state.db not found at {db_path}. Run bootstrap --init-db first.")
        return 1

    lock_path = cfg.abs_path("data/.gen_run.lock")
    try:
        with acquire_run_lock(lock_path):
            conn = connect(db_path)
            repo = Repository(conn)
            try:
                openrouter_api_key = os.environ.get("OPENROUTER_API_KEY")
                ollama_host = os.environ.get("OLLAMA_HOST")
                success, summary = run_generation(
                    repo=repo, cfg=cfg, clips_n=args.clips_n,
                    dry_run=args.dry_run,
                    openrouter_api_key=openrouter_api_key,
                    ollama_host=ollama_host,
                )
                print(json.dumps(summary, indent=2))
                return 0 if success else 1
            except Exception:
                return 1
            finally:
                conn.close()
    except RunLockHeld:
        append_alert(
            logs_dir, kind="lock_held",
            message="gen_run skipped: another instance holds data/.gen_run.lock",
        )
        logger.warning("gen_run: lock_held; another instance is running")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
