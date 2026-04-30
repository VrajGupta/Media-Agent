"""Phase 2.5 lang_detect tests.

Strategy: monkeypatch `src.lang_detect.runner.WhisperModel` to a stub that
returns a canned (lang, prob) tuple so no GPU/CUDA is touched. With the
patch in place, `LangDetector(cfg)` is safe to instantiate.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.lang_detect import runner
from src.lang_detect.runner import (
    LangDetectModelLoadError,
    LangDetectOutcome,
    LangDetector,
    detect_one,
    run_all,
)
from src.state import Repository, connect, initialize_schema
from tests.conftest import StubConfig


def _seed(repo: Repository, vid: str, status: str = "downloaded") -> None:
    repo.discovery_upsert_video(
        video_id=vid, title="T", channel="C",
        duration_seconds=600, views=100, likes=1, comments=1,
        published_at="2026-04-01T00:00:00Z",
        keyword="k", virality_score=1.5,
    )
    if status != "discovered":
        repo.set_video_status(vid, status)


def _touch_raw(cfg: StubConfig, vid: str, size: int = 1000) -> None:
    raw_dir = Path(cfg.paths.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{vid}.mp4").write_bytes(b"\x00" * size)


def _patch_whisper(monkeypatch, lang: str, prob: float):
    """Patch WhisperModel to a stub returning a canned (lang, prob)."""

    class StubModel:
        def __init__(self, *a, **kw):
            pass

        def transcribe(self, *a, **kw):
            info = SimpleNamespace(language=lang, language_probability=prob)
            return iter([]), info

    monkeypatch.setattr(runner, "WhisperModel", StubModel)


def _patch_whisper_raises(monkeypatch, exc: Exception):
    """Patch WhisperModel to a stub whose transcribe() raises."""

    class StubModel:
        def __init__(self, *a, **kw):
            pass

        def transcribe(self, *a, **kw):
            raise exc

    monkeypatch.setattr(runner, "WhisperModel", StubModel)


def _patch_whisper_ctor_raises(monkeypatch, exc: Exception):
    """Patch WhisperModel so __init__ itself raises (model-load failure)."""

    class StubModel:
        def __init__(self, *a, **kw):
            raise exc

    monkeypatch.setattr(runner, "WhisperModel", StubModel)


def _setup(tmp_path, monkeypatch, lang: str, prob: float, vid: str = "v1", status: str = "downloaded"):
    cfg = StubConfig(tmp_path)
    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn); repo = Repository(conn)
    _seed(repo, vid, status=status)
    _touch_raw(cfg, vid)
    _patch_whisper(monkeypatch, lang, prob)
    detector = LangDetector(cfg)
    return cfg, repo, detector


# ---- 1-5: language verdicts ------------------------------------------------


def test_english_high_conf_passes(tmp_path, monkeypatch):
    cfg, repo, det = _setup(tmp_path, monkeypatch, "en", 0.95)
    r = detect_one(det, repo, cfg, "v1")
    assert r.outcome == LangDetectOutcome.passed_lang_ok
    assert repo.get_video("v1")["status"] == "lang_ok"


def test_english_low_conf_passes(tmp_path, monkeypatch):
    cfg, repo, det = _setup(tmp_path, monkeypatch, "en", 0.30)
    r = detect_one(det, repo, cfg, "v1")
    assert r.outcome == LangDetectOutcome.passed_lang_ok
    assert repo.get_video("v1")["status"] == "lang_ok"


def test_spanish_high_conf_rejects(tmp_path, monkeypatch):
    cfg, repo, det = _setup(tmp_path, monkeypatch, "es", 0.92)
    r = detect_one(det, repo, cfg, "v1")
    assert r.outcome == LangDetectOutcome.rejected_language
    row = repo.get_video("v1")
    assert row["status"] == "rejected_language"
    assert "lang=es" in row["rejection_reason"]
    assert "conf=0.92" in row["rejection_reason"]


def test_german_low_conf_passes(tmp_path, monkeypatch):
    """Low-confidence non-English gets benefit of the doubt."""
    cfg, repo, det = _setup(tmp_path, monkeypatch, "de", 0.40)
    r = detect_one(det, repo, cfg, "v1")
    assert r.outcome == LangDetectOutcome.passed_lang_ok
    assert repo.get_video("v1")["status"] == "lang_ok"


def test_boundary_threshold_rejects(tmp_path, monkeypatch):
    """conf == threshold should reject (>= comparison)."""
    cfg, repo, det = _setup(tmp_path, monkeypatch, "es", 0.70)
    r = detect_one(det, repo, cfg, "v1")
    assert r.outcome == LangDetectOutcome.rejected_language


# ---- 6-9: status preflight + force ----------------------------------------


def test_wrong_status_skips(tmp_path, monkeypatch):
    cfg, repo, det = _setup(tmp_path, monkeypatch, "en", 0.95, status="discovered")
    r = detect_one(det, repo, cfg, "v1")
    assert r.outcome == LangDetectOutcome.skipped_wrong_status
    assert repo.get_video("v1")["status"] == "discovered"


def test_already_lang_ok_no_force_skips(tmp_path, monkeypatch):
    cfg, repo, det = _setup(tmp_path, monkeypatch, "en", 0.95, status="lang_ok")
    r = detect_one(det, repo, cfg, "v1")
    assert r.outcome == LangDetectOutcome.skipped_already_lang_ok


def test_force_repass_skips_db_write(tmp_path, monkeypatch):
    """--force on lang_ok that re-passes must not bump updated_at."""
    cfg, repo, det = _setup(tmp_path, monkeypatch, "en", 0.95, status="lang_ok")
    before = repo.get_video("v1")["updated_at"]
    r = detect_one(det, repo, cfg, "v1", force=True)
    assert r.outcome == LangDetectOutcome.passed_lang_ok
    after = repo.get_video("v1")["updated_at"]
    assert before == after  # no write


def test_force_flips_lang_ok_to_rejected(tmp_path, monkeypatch):
    """--force can reverse a prior pass when threshold/content drifts."""
    cfg, repo, det = _setup(tmp_path, monkeypatch, "es", 0.85, status="lang_ok")
    r = detect_one(det, repo, cfg, "v1", force=True)
    assert r.outcome == LangDetectOutcome.rejected_language
    row = repo.get_video("v1")
    assert row["status"] == "rejected_language"
    assert "lang=es" in row["rejection_reason"]


# ---- 10-12: file + inference + dry-run ------------------------------------


def test_missing_raw_file_skips(tmp_path, monkeypatch):
    cfg = StubConfig(tmp_path)
    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn); repo = Repository(conn)
    _seed(repo, "v1")  # status=downloaded but no file
    _patch_whisper(monkeypatch, "en", 0.95)
    det = LangDetector(cfg)

    r = detect_one(det, repo, cfg, "v1")
    assert r.outcome == LangDetectOutcome.skipped_missing_file
    assert repo.get_video("v1")["status"] == "downloaded"  # unchanged


def test_inference_error_leaves_status_unchanged(tmp_path, monkeypatch):
    cfg = StubConfig(tmp_path)
    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn); repo = Repository(conn)
    _seed(repo, "v1")
    _touch_raw(cfg, "v1")
    _patch_whisper_raises(monkeypatch, RuntimeError("CUDA OOM"))
    det = LangDetector(cfg)

    r = detect_one(det, repo, cfg, "v1")
    assert r.outcome == LangDetectOutcome.error_inference
    assert "CUDA OOM" in (r.reason or "")
    assert repo.get_video("v1")["status"] == "downloaded"  # unchanged for retry


def test_dry_run_skips_db_write(tmp_path, monkeypatch):
    cfg, repo, det = _setup(tmp_path, monkeypatch, "es", 0.90)
    before = repo.get_video("v1")["updated_at"]
    r = detect_one(det, repo, cfg, "v1", dry_run=True)
    assert r.outcome == LangDetectOutcome.rejected_language
    after = repo.get_video("v1")["updated_at"]
    assert before == after  # no write
    assert repo.get_video("v1")["status"] == "downloaded"  # unchanged


# ---- 13-14: run_all batch behavior ----------------------------------------


def test_run_all_zero_candidates_does_not_load_model(tmp_path, monkeypatch):
    """When the candidate set is empty, WhisperModel must not be constructed."""
    cfg = StubConfig(tmp_path)
    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn); repo = Repository(conn)
    # No videos seeded -> empty candidate set.

    sentinel_calls = []

    class TripwireModel:
        def __init__(self, *a, **kw):
            sentinel_calls.append(("init", a, kw))
            raise AssertionError("WhisperModel must not be constructed when there are no candidates")

    monkeypatch.setattr(runner, "WhisperModel", TripwireModel)

    results = run_all(repo, cfg)
    assert results == []
    assert sentinel_calls == []


def test_run_all_model_load_failure_raises(tmp_path, monkeypatch):
    cfg = StubConfig(tmp_path)
    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn); repo = Repository(conn)
    _seed(repo, "v1")
    _touch_raw(cfg, "v1")
    _patch_whisper_ctor_raises(monkeypatch, RuntimeError("missing cuDNN"))

    with pytest.raises(LangDetectModelLoadError) as excinfo:
        run_all(repo, cfg)
    assert "missing cuDNN" in str(excinfo.value)
    # Status not touched on model-load failure.
    assert repo.get_video("v1")["status"] == "downloaded"
