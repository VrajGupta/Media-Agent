"""Language detection orchestration (Phase 2.5).

Per-video flow:
  preflight status -> resolve raw path -> Whisper probe ->
  apply reject rule -> status update.

Sequential. Whisper model loaded once per batch and reused.
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


def _preload_nvidia_dlls() -> None:
    """On Windows, nvidia-* pip wheels ship cublas/cudnn DLLs inside site-packages
    but ctranslate2's compiled extension uses LoadLibrary calls that don't pick
    them up via `os.add_dll_directory` alone. We register the dirs AND eagerly
    preload the required DLLs by absolute path so they are resident in the
    process address space before ctranslate2's first GPU operation."""
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
                # missing optional DLL is non-fatal; primary cublas64_12 is the one
                # ctranslate2 actually needs.
                pass


_preload_nvidia_dlls()

from faster_whisper import WhisperModel  # noqa: E402  (must follow DLL registration)
from loguru import logger

from src.config_loader import Config
from src.state import Repository


class LangDetectModelLoadError(Exception):
    """Raised when WhisperModel construction fails. CLI handles logging + exit."""


class LangDetectOutcome(str, Enum):
    passed_lang_ok = "passed_lang_ok"
    rejected_language = "rejected_language"
    skipped_wrong_status = "skipped_wrong_status"
    skipped_already_lang_ok = "skipped_already_lang_ok"
    skipped_missing_file = "skipped_missing_file"
    error_inference = "error_inference"


@dataclass
class LangDetectResult:
    video_id: str
    outcome: LangDetectOutcome
    detected_lang: Optional[str] = None
    confidence: Optional[float] = None
    reason: Optional[str] = None


def preflight_status(row: sqlite3.Row, force: bool) -> Optional[LangDetectOutcome]:
    """Decide whether a row needs detection without touching Whisper.

    Returns a skip outcome if the row should bypass detection entirely, or
    None when the caller should proceed and run Whisper.
    """
    status = row["status"]
    if status not in ("downloaded", "lang_ok"):
        return LangDetectOutcome.skipped_wrong_status
    if status == "lang_ok" and not force:
        return LangDetectOutcome.skipped_already_lang_ok
    return None


class LangDetector:
    """Single-shot Whisper wrapper. Loads the model once; reused across videos."""

    def __init__(self, cfg: Config) -> None:
        self.model = WhisperModel(
            cfg.whisper_model,
            device=cfg.whisper_device,
            compute_type=cfg.whisper_compute_type,
        )
        self.threshold = cfg.lang_detect_threshold
        self.target = cfg.lang_detect_target_lang

    def detect(self, video_path: Path) -> tuple[str, float]:
        # We do not iterate `segments`, so Whisper performs language detection
        # on the initial encoder window and returns without full transcription.
        segments, info = self.model.transcribe(
            str(video_path),
            beam_size=1,
            language=None,
            vad_filter=False,
        )
        return info.language, float(info.language_probability)


def detect_one(
    detector: LangDetector,
    repo: Repository,
    cfg: Config,
    video_id: str,
    force: bool = False,
    dry_run: bool = False,
) -> LangDetectResult:
    row = repo.get_video(video_id)
    if row is None:
        # Defensive: __main__.py guards this for single-video; run_all only
        # iterates rows it just queried, so this path is rare.
        logger.warning(f"video_id {video_id} not in DB")
        return LangDetectResult(video_id, LangDetectOutcome.skipped_wrong_status)

    skip = preflight_status(row, force)
    if skip is not None:
        return LangDetectResult(video_id, skip)

    raw_path = cfg.abs_path(cfg.paths.raw_dir) / f"{video_id}.mp4"
    if not raw_path.exists() or raw_path.stat().st_size == 0:
        logger.warning(f"raw file missing for {video_id}: {raw_path}")
        return LangDetectResult(video_id, LangDetectOutcome.skipped_missing_file)

    try:
        lang, confidence = detector.detect(raw_path)
    except Exception as exc:
        logger.exception(f"lang_detect inference failed: {video_id}")
        return LangDetectResult(
            video_id,
            LangDetectOutcome.error_inference,
            reason=str(exc)[:200],
        )

    target = detector.target
    threshold = detector.threshold
    reject = (lang != target) and (confidence >= threshold)

    if reject:
        reason = f"lang={lang}, conf={confidence:.2f}"
        if not dry_run:
            repo.set_video_status(video_id, "rejected_language", reason=reason)
        logger.info(f"rejected_language: {video_id} ({reason})")
        return LangDetectResult(
            video_id,
            LangDetectOutcome.rejected_language,
            detected_lang=lang,
            confidence=confidence,
            reason=reason,
        )

    # Pass: only write if status would actually change. Avoids gratuitously
    # bumping updated_at or nulling rejection_reason on --force re-pass.
    if not dry_run and row["status"] != "lang_ok":
        repo.set_video_status(video_id, "lang_ok")
    logger.info(f"lang_ok: {video_id} (lang={lang}, conf={confidence:.2f})")
    return LangDetectResult(
        video_id,
        LangDetectOutcome.passed_lang_ok,
        detected_lang=lang,
        confidence=confidence,
    )


def run_all(
    repo: Repository,
    cfg: Config,
    force: bool = False,
    dry_run: bool = False,
) -> list[LangDetectResult]:
    if force:
        rows = repo.videos_with_statuses(["downloaded", "lang_ok"])
    else:
        rows = repo.videos_by_status("downloaded")

    if not rows:
        logger.info("lang_detect: no candidates")
        return []

    try:
        detector = LangDetector(cfg)
    except Exception as exc:
        raise LangDetectModelLoadError(str(exc)) from exc

    results: list[LangDetectResult] = []
    for row in rows:
        result = detect_one(detector, repo, cfg, row["video_id"], force=force, dry_run=dry_run)
        results.append(result)

    counts: dict[str, int] = {}
    for r in results:
        counts[r.outcome.value] = counts.get(r.outcome.value, 0) + 1
    passed = counts.get(LangDetectOutcome.passed_lang_ok.value, 0)
    rejected = counts.get(LangDetectOutcome.rejected_language.value, 0)
    skipped = (
        counts.get(LangDetectOutcome.skipped_wrong_status.value, 0)
        + counts.get(LangDetectOutcome.skipped_already_lang_ok.value, 0)
        + counts.get(LangDetectOutcome.skipped_missing_file.value, 0)
    )
    errors = counts.get(LangDetectOutcome.error_inference.value, 0)
    logger.info(f"lang_detect summary: passed={passed} rejected={rejected} skipped={skipped} errors={errors}")
    return results
