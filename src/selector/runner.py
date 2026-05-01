"""Selector orchestration (Phase 3).

Per-video flow:
  preflight status -> resolve raw path -> [transcribe or load cache] ->
  flip status to 'transcribed' -> heatmap fetch -> build windows ->
  rank via Ollama -> upsert clip rows + flip status to 'selected'.

Whisper model loaded once per batch and reused. Ollama keeps the qwen2.5:3b-instruct
model resident via keep_alive=10m across the per-video calls.

Failure handling:
  - Whisper inference error  -> status stays 'lang_ok', no transcript file written.
  - Heatmap None             -> selection_method='transcript_only', not an error.
  - Ranker RankerError       -> status stays 'transcribed', alert at run end.
  - Whisper model load fail  -> SelectorModelLoadError, run aborted (CLI alerts).
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


def _preload_nvidia_dlls() -> None:
    """Mirror of lang_detect's DLL preload — required because ctranslate2's
    compiled extension doesn't honor os.add_dll_directory alone on Windows."""
    if sys.platform != "win32":
        return
    import ctypes
    pkg_dlls = {
        "nvidia.cublas": ["cublas64_12.dll", "cublasLt64_12.dll"],
        "nvidia.cudnn": [
            "cudnn64_9.dll", "cudnn_ops64_9.dll", "cudnn_cnn64_9.dll",
            "cudnn_graph64_9.dll", "cudnn_engines_precompiled64_9.dll",
        ],
        "nvidia.cuda_nvrtc": [],
    }
    for pkg, dlls in pkg_dlls.items():
        spec = importlib.util.find_spec(pkg)
        if spec is None or not spec.submodule_search_locations:
            continue
        dll_dir = Path(spec.submodule_search_locations[0]) / "bin"
        if not dll_dir.is_dir():
            continue
        os.add_dll_directory(str(dll_dir))
        for name in dlls:
            try:
                ctypes.WinDLL(str(dll_dir / name))
            except OSError:
                pass


_preload_nvidia_dlls()

from faster_whisper import WhisperModel  # noqa: E402
from loguru import logger  # noqa: E402

from src.config_loader import Config  # noqa: E402
from src.observability import append_alert  # noqa: E402
from src.selector import heatmap as heatmap_mod  # noqa: E402
from src.selector import ranker as ranker_mod  # noqa: E402
from src.selector import transcriber as transcriber_mod  # noqa: E402
from src.selector.windows import HeatMarker, build_windows, cap_candidates  # noqa: E402
from src.state import Repository  # noqa: E402


class SelectorModelLoadError(Exception):
    pass


class SelectorOutcome(str, Enum):
    selected = "selected"
    skipped_wrong_status = "skipped_wrong_status"
    skipped_already_selected = "skipped_already_selected"
    skipped_missing_file = "skipped_missing_file"
    error_transcribe = "error_transcribe"
    error_rank = "error_rank"
    error_no_windows = "error_no_windows"


@dataclass
class SelectorResult:
    video_id: str
    outcome: SelectorOutcome
    selection_method: Optional[str] = None       # heatmap_aided | transcript_only | mixed
    heatmap_fetched: bool = False                # for run-level hit_rate
    n_windows: int = 0
    n_clips_selected: int = 0
    reason: Optional[str] = None


@dataclass
class _BatchAlerts:
    """Run-end rolled-up alerts (matches lang_detect's batch alert pattern)."""
    transcribe_errors: list[str] = field(default_factory=list)
    rank_errors: list[str] = field(default_factory=list)


def preflight_status(
    row: sqlite3.Row,
    *,
    force: bool,
    retranscribe: bool,
) -> Optional[SelectorOutcome]:
    """Return a skip outcome if the row should bypass selection, else None."""
    status = row["status"]
    if status not in ("lang_ok", "transcribed", "selected"):
        return SelectorOutcome.skipped_wrong_status
    if status == "selected" and not (force or retranscribe):
        return SelectorOutcome.skipped_already_selected
    return None


def _ensure_transcript(
    *,
    repo: Repository,
    cfg: Config,
    video_id: str,
    raw_path: Path,
    transcripts_dir: Path,
    whisper_model_loader,
    retranscribe: bool,
    dry_run: bool,
) -> tuple[Optional[transcriber_mod.Transcript], Optional[str]]:
    """Returns (transcript, error_reason). Either transcribe or load from cache."""
    if not retranscribe:
        cached = transcriber_mod.read_cached(
            transcripts_dir, video_id, cfg.whisper_model, cfg.whisper_compute_type
        )
        if cached is not None:
            logger.info(f"transcript cache hit: {video_id}")
            if not dry_run and repo.get_video(video_id)["status"] == "lang_ok":
                repo.set_video_status(video_id, "transcribed")
            return cached, None

    model = whisper_model_loader()
    try:
        transcript = transcriber_mod.run_whisper(
            model, raw_path, video_id, cfg.whisper_model, cfg.whisper_compute_type
        )
    except Exception as exc:
        logger.exception(f"whisper inference failed: {video_id}")
        return None, str(exc)[:200]

    if not dry_run:
        try:
            transcriber_mod.atomic_write(transcripts_dir, transcript)
        except Exception as exc:
            logger.exception(f"transcript cache write failed: {video_id}")
            return None, f"cache write failed: {str(exc)[:180]}"
        repo.set_video_status(video_id, "transcribed")

    return transcript, None


def select_one_video(
    *,
    repo: Repository,
    cfg: Config,
    video_id: str,
    whisper_model_loader,
    force: bool = False,
    retranscribe: bool = False,
    dry_run: bool = False,
) -> SelectorResult:
    row = repo.get_video(video_id)
    if row is None:
        logger.warning(f"video_id {video_id} not in DB")
        return SelectorResult(video_id, SelectorOutcome.skipped_wrong_status)

    skip = preflight_status(row, force=force, retranscribe=retranscribe)
    if skip is not None:
        return SelectorResult(video_id, skip)

    raw_path = cfg.abs_path(cfg.paths.raw_dir) / f"{video_id}.mp4"
    if not raw_path.exists() or raw_path.stat().st_size == 0:
        logger.warning(f"raw file missing for {video_id}: {raw_path}")
        return SelectorResult(video_id, SelectorOutcome.skipped_missing_file)

    transcripts_dir = cfg.abs_path(cfg.paths.transcripts_dir)
    transcript, terr = _ensure_transcript(
        repo=repo,
        cfg=cfg,
        video_id=video_id,
        raw_path=raw_path,
        transcripts_dir=transcripts_dir,
        whisper_model_loader=whisper_model_loader,
        retranscribe=retranscribe,
        dry_run=dry_run,
    )
    if transcript is None:
        return SelectorResult(video_id, SelectorOutcome.error_transcribe, reason=terr)

    # Heatmap fetch (network — None means fail-open miss).
    markers = heatmap_mod.fetch_heatmap(video_id)
    heatmap_fetched = markers is not None and len(markers) > 0
    markers_for_windows: list[HeatMarker] = list(markers) if markers else []

    windows = build_windows(
        transcript.segments,
        markers=markers_for_windows or None,
        min_seconds=float(cfg.clip_min_seconds),
        max_seconds=float(cfg.clip_max_seconds),
    )
    raw_window_count = len(windows)
    if windows:
        windows = cap_candidates(windows, cfg.selector_max_candidates)
        if len(windows) < raw_window_count:
            logger.info(
                f"capped candidates for {video_id}: "
                f"{raw_window_count} -> {len(windows)} (max={cfg.selector_max_candidates})"
            )
    if not windows:
        logger.info(f"no candidate windows for {video_id} (video too short or sparse)")
        return SelectorResult(
            video_id,
            SelectorOutcome.error_no_windows,
            heatmap_fetched=heatmap_fetched,
            n_windows=0,
        )

    try:
        ranked = ranker_mod.rank_windows(
            windows,
            model=cfg.ollama_model,
            top_n=cfg.clips_per_video,
        )
    except ranker_mod.RankerError as exc:
        return SelectorResult(
            video_id,
            SelectorOutcome.error_rank,
            heatmap_fetched=heatmap_fetched,
            n_windows=len(windows),
            reason=str(exc)[:200],
        )

    by_id = {w.candidate_id: w for w in windows}
    methods: list[str] = []
    if not dry_run:
        with repo.tx():
            for rc in ranked:
                w = by_id[rc.candidate_id]
                method = "heatmap_aided" if w.heatmap_peak else "transcript_only"
                methods.append(method)
                clip_id = f"{video_id}_{int(w.start_s)}_{int(w.end_s)}"
                repo.upsert_selector_clip(
                    clip_id=clip_id,
                    video_id=video_id,
                    start_s=w.start_s,
                    end_s=w.end_s,
                    hook=rc.hook,
                    suggested_title=rc.suggested_title,
                    selection_method=method,
                )
            repo.set_video_status(video_id, "selected")
    else:
        for rc in ranked:
            w = by_id[rc.candidate_id]
            methods.append("heatmap_aided" if w.heatmap_peak else "transcript_only")

    if all(m == "heatmap_aided" for m in methods):
        agg_method = "heatmap_aided"
    elif all(m == "transcript_only" for m in methods):
        agg_method = "transcript_only"
    else:
        agg_method = "mixed"

    logger.info(
        f"selected {len(ranked)} clips for {video_id} "
        f"(method={agg_method}, windows={len(windows)})"
    )
    return SelectorResult(
        video_id,
        SelectorOutcome.selected,
        selection_method=agg_method,
        heatmap_fetched=heatmap_fetched,
        n_windows=len(windows),
        n_clips_selected=len(ranked),
    )


def _make_whisper_loader(cfg: Config):
    """Lazy loader so an empty candidate set never instantiates WhisperModel."""
    state = {"model": None}

    def _load():
        if state["model"] is None:
            try:
                state["model"] = WhisperModel(
                    cfg.whisper_model,
                    device=cfg.whisper_device,
                    compute_type=cfg.whisper_compute_type,
                )
            except Exception as exc:
                raise SelectorModelLoadError(str(exc)) from exc
        return state["model"]

    return _load


def _emit_heatmap_qa_template(
    cfg: Config,
    repo: Repository,
    results: list[SelectorResult],
) -> None:
    """Append a 5+5 review template row to logs/heatmap_qa.md."""
    transcript_only_ids: list[str] = []
    heatmap_aided_ids: list[str] = []
    for r in results:
        if r.outcome != SelectorOutcome.selected:
            continue
        rows = repo.conn.execute(
            "SELECT clip_id, selection_method, hook FROM clips "
            "WHERE video_id=? AND status='selected'",
            (r.video_id,),
        ).fetchall()
        for row in rows:
            if row["selection_method"] == "transcript_only" and len(transcript_only_ids) < 5:
                transcript_only_ids.append((row["clip_id"], row["hook"]))
            elif row["selection_method"] == "heatmap_aided" and len(heatmap_aided_ids) < 5:
                heatmap_aided_ids.append((row["clip_id"], row["hook"]))

    if not transcript_only_ids and not heatmap_aided_ids:
        return

    qa_path = cfg.abs_path(cfg.paths.logs_dir) / "heatmap_qa.md"
    qa_path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not qa_path.exists()
    from datetime import datetime, timezone
    week = datetime.now(timezone.utc).strftime("%Y-W%U")

    with qa_path.open("a", encoding="utf-8") as f:
        if new_file:
            f.write("# Heatmap QA — manual reviewer spot-check\n\n")
            f.write("Rate each clip 1–5 on 'watchable hook'. Mean rating per group ")
            f.write("informs whether the heatmap signal is worth the dependency.\n\n")
        f.write(f"## Week {week}\n\n")
        f.write("| clip_id | selection_method | hook | rating_1_to_5 | notes |\n")
        f.write("| --- | --- | --- | --- | --- |\n")
        for cid, hook in heatmap_aided_ids:
            safe_hook = hook.replace("|", "\\|").replace("\n", " ")[:80]
            f.write(f"| {cid} | heatmap_aided | {safe_hook} |  |  |\n")
        for cid, hook in transcript_only_ids:
            safe_hook = hook.replace("|", "\\|").replace("\n", " ")[:80]
            f.write(f"| {cid} | transcript_only | {safe_hook} |  |  |\n")
        f.write("\n")


def run_all(
    repo: Repository,
    cfg: Config,
    *,
    force: bool = False,
    retranscribe: bool = False,
    dry_run: bool = False,
) -> list[SelectorResult]:
    if force or retranscribe:
        rows = repo.videos_with_statuses(["lang_ok", "transcribed", "selected"])
    else:
        rows = repo.videos_with_statuses(["lang_ok", "transcribed"])

    if not rows:
        logger.info("selector: no candidates")
        return []

    whisper_loader = _make_whisper_loader(cfg)
    alerts = _BatchAlerts()
    results: list[SelectorResult] = []

    for row in rows:
        try:
            result = select_one_video(
                repo=repo,
                cfg=cfg,
                video_id=row["video_id"],
                whisper_model_loader=whisper_loader,
                force=force,
                retranscribe=retranscribe,
                dry_run=dry_run,
            )
        except SelectorModelLoadError:
            raise
        results.append(result)
        if result.outcome == SelectorOutcome.error_transcribe:
            alerts.transcribe_errors.append(f"{result.video_id}: {result.reason}")
        elif result.outcome == SelectorOutcome.error_rank:
            alerts.rank_errors.append(f"{result.video_id}: {result.reason}")

    # Run-level heatmap hit-rate alert.
    attempted = sum(1 for r in results if r.outcome in (
        SelectorOutcome.selected, SelectorOutcome.error_rank, SelectorOutcome.error_no_windows
    ))
    fetched = sum(1 for r in results if r.heatmap_fetched)
    if attempted > 0:
        hit_rate = fetched / attempted
        logger.info(f"heatmap_hit_rate: {fetched}/{attempted} = {hit_rate:.1%}")
        if hit_rate < 0.70:
            append_alert(
                cfg.abs_path(cfg.paths.logs_dir),
                kind="heatmap_low_hit_rate",
                message=f"heatmap_hit_rate={hit_rate:.1%} (<70%); {fetched} of {attempted} videos had heatmap data",
            )

    if alerts.transcribe_errors:
        append_alert(
            cfg.abs_path(cfg.paths.logs_dir),
            kind="selector_transcribe_errors",
            message=f"{len(alerts.transcribe_errors)} videos failed transcription; first: {alerts.transcribe_errors[0]}",
        )
    if alerts.rank_errors:
        append_alert(
            cfg.abs_path(cfg.paths.logs_dir),
            kind="selector_rank_errors",
            message=f"{len(alerts.rank_errors)} videos failed ranking; first: {alerts.rank_errors[0]}",
        )

    if not dry_run:
        _emit_heatmap_qa_template(cfg, repo, results)

    selected_count = sum(1 for r in results if r.outcome == SelectorOutcome.selected)
    logger.info(
        f"selector summary: selected={selected_count} "
        f"transcribe_err={len(alerts.transcribe_errors)} "
        f"rank_err={len(alerts.rank_errors)} "
        f"total={len(results)}"
    )
    return results
