"""End-to-end selector orchestration: status flow, idempotency, alerts.

Whisper + heatmap + Ollama all monkeypatched. No GPU/network touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from src.selector import heatmap as heatmap_mod
from src.selector import ranker as ranker_mod
from src.selector import runner as runner_mod
from src.selector import transcriber as transcriber_mod
from src.selector.runner import (
    SelectorModelLoadError,
    SelectorOutcome,
    run_all,
    select_one_video,
)
from src.state import Repository, connect, initialize_schema
from tests.conftest import StubConfig


# ---- Whisper / Ollama / heatmap fakes --------------------------------------


def _stub_word(start: float, end: float, word: str, prob: float = 0.9):
    return SimpleNamespace(start=start, end=end, word=word, probability=prob)


def _stub_segment(start: float, end: float, text: str, words: list):
    return SimpleNamespace(start=start, end=end, text=text, words=words)


def _make_segments(n: int = 10, length_each: float = 10.0):
    return [
        _stub_segment(
            i * length_each, (i + 1) * length_each, f"seg{i} content here for ranking",
            [_stub_word(i * length_each, i * length_each + 1, f"word{i}")],
        )
        for i in range(n)
    ]


class StubWhisperModel:
    def __init__(self, *a, segments=None, **kw):
        self._segments = segments if segments is not None else _make_segments()

    def transcribe(self, *a, **kw):
        info = SimpleNamespace(language="en", language_probability=0.95, duration=100.0)
        return iter(self._segments), info


class TripwireWhisperModel:
    """Constructing this class is a test failure."""
    def __init__(self, *a, **kw):
        raise AssertionError("WhisperModel must NOT be constructed in this test")


class RaisingCtorWhisperModel:
    def __init__(self, *a, **kw):
        raise RuntimeError("missing cuDNN")


class TranscribeRaisesModel:
    def __init__(self, *a, **kw):
        pass

    def transcribe(self, *a, **kw):
        info = SimpleNamespace(language="en", language_probability=0.95, duration=100.0)

        def _gen():
            yield _stub_segment(0.0, 5.0, "hi", [_stub_word(0.0, 1.0, "hi")])
            raise RuntimeError("simulated CUDA OOM")

        return _gen(), info


def _patch_whisper(monkeypatch, model_cls):
    monkeypatch.setattr(runner_mod, "WhisperModel", model_cls)


def _patch_heatmap_returns(monkeypatch, value):
    """value can be: list[HeatMarker], [], None, or a callable(video_id)->value."""
    if callable(value):
        monkeypatch.setattr(heatmap_mod, "fetch_heatmap", value)
    else:
        monkeypatch.setattr(heatmap_mod, "fetch_heatmap", lambda vid: value)


def _patch_ranker_returns(monkeypatch, ranked_clips):
    """ranked_clips can be a list[RankedClip], a callable, or an Exception class."""
    if isinstance(ranked_clips, Exception):
        def _raise(*a, **kw):
            raise ranked_clips
        monkeypatch.setattr(ranker_mod, "rank_windows", _raise)
    elif callable(ranked_clips):
        monkeypatch.setattr(ranker_mod, "rank_windows", ranked_clips)
    else:
        def _ret(*a, **kw):
            return list(ranked_clips)
        monkeypatch.setattr(ranker_mod, "rank_windows", _ret)


# ---- DB / cfg helpers ------------------------------------------------------


def _make_cfg_with_paths(tmp_path: Path) -> StubConfig:
    """Extend StubConfig with selector-specific config attrs."""
    cfg = StubConfig(tmp_path)
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir(parents=True, exist_ok=True)
    pending = tmp_path / "output" / "pending"
    pending.mkdir(parents=True, exist_ok=True)

    cfg.paths.transcripts_dir = str(transcripts)
    cfg.paths.pending_dir = str(pending)
    # Selector knobs.
    cfg.clip_min_seconds = 30
    cfg.clip_max_seconds = 60
    cfg.clips_per_video = 2
    cfg.ollama_model = "qwen2.5:3b-instruct"
    return cfg


def _seed_video(repo: Repository, vid: str = "v1", status: str = "lang_ok") -> None:
    repo.discovery_upsert_video(
        video_id=vid, title="T", channel="C",
        duration_seconds=600, views=100, likes=1, comments=1,
        published_at="2026-04-01T00:00:00Z",
        keyword="k", virality_score=1.5,
    )
    if status != "discovered":
        repo.set_video_status(vid, status)


def _touch_raw(cfg: StubConfig, vid: str = "v1") -> None:
    raw = Path(cfg.paths.raw_dir) / f"{vid}.mp4"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(b"\x00" * 1000)


def _setup(tmp_path, vid: str = "v1", status: str = "lang_ok"):
    cfg = _make_cfg_with_paths(tmp_path)
    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn)
    repo = Repository(conn)
    _seed_video(repo, vid, status=status)
    _touch_raw(cfg, vid)
    return cfg, repo


def _two_clips(c0: str = "c0", c1: str = "c1"):
    return [
        ranker_mod.RankedClip(candidate_id=c0, hook="hook A", suggested_title="Title A", score=9.0),
        ranker_mod.RankedClip(candidate_id=c1, hook="hook B", suggested_title="Title B", score=8.0),
    ]


# ---- Status preflight matrix -----------------------------------------------


def test_lang_ok_proceeds_to_selected(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    _patch_whisper(monkeypatch, StubWhisperModel)
    _patch_heatmap_returns(monkeypatch, None)
    _patch_ranker_returns(monkeypatch, _two_clips())

    r = select_one_video(
        repo=repo, cfg=cfg, video_id="v1",
        whisper_model_loader=runner_mod._make_whisper_loader(cfg),
    )
    assert r.outcome == SelectorOutcome.selected
    assert repo.get_video("v1")["status"] == "selected"
    clips = repo.conn.execute("SELECT * FROM clips WHERE video_id='v1'").fetchall()
    assert len(clips) == 2


def test_discovered_status_skipped(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path, status="discovered")
    _patch_whisper(monkeypatch, TripwireWhisperModel)
    _patch_heatmap_returns(monkeypatch, None)
    r = select_one_video(
        repo=repo, cfg=cfg, video_id="v1",
        whisper_model_loader=runner_mod._make_whisper_loader(cfg),
    )
    assert r.outcome == SelectorOutcome.skipped_wrong_status


def test_already_selected_no_force_skips(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path, status="selected")
    _patch_whisper(monkeypatch, TripwireWhisperModel)
    _patch_heatmap_returns(monkeypatch, None)
    r = select_one_video(
        repo=repo, cfg=cfg, video_id="v1",
        whisper_model_loader=runner_mod._make_whisper_loader(cfg),
    )
    assert r.outcome == SelectorOutcome.skipped_already_selected


# ---- Cache + force semantics -----------------------------------------------


def test_force_rerank_uses_cache_no_whisper_load(tmp_path, monkeypatch):
    """--force re-runs ranking but reuses cached transcript — Whisper must NOT load."""
    cfg, repo = _setup(tmp_path, status="selected")
    # Pre-populate cache.
    transcripts_dir = Path(cfg.paths.transcripts_dir)
    cached = transcriber_mod.Transcript(
        video_id="v1", model="large-v3", compute_type="int8_float16",
        duration_seconds=100.0, language="en", language_probability=0.99,
        segments=[
            {"start": i * 10.0, "end": (i + 1) * 10.0, "text": f"seg{i}", "words": []}
            for i in range(10)
        ],
    )
    transcriber_mod.atomic_write(transcripts_dir, cached)

    _patch_whisper(monkeypatch, TripwireWhisperModel)  # Tripwire!
    _patch_heatmap_returns(monkeypatch, None)
    _patch_ranker_returns(monkeypatch, _two_clips())

    r = select_one_video(
        repo=repo, cfg=cfg, video_id="v1",
        whisper_model_loader=runner_mod._make_whisper_loader(cfg),
        force=True,
    )
    assert r.outcome == SelectorOutcome.selected


def test_retranscribe_invokes_whisper_even_with_cache(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path, status="selected")
    transcripts_dir = Path(cfg.paths.transcripts_dir)
    cached = transcriber_mod.Transcript(
        video_id="v1", model="large-v3", compute_type="int8_float16",
        duration_seconds=100.0, language="en", language_probability=0.99,
        segments=[{"start": 0, "end": 5, "text": "old", "words": []}],
    )
    transcriber_mod.atomic_write(transcripts_dir, cached)

    invoked = {"n": 0}

    class CountingModel(StubWhisperModel):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            invoked["n"] += 1

    _patch_whisper(monkeypatch, CountingModel)
    _patch_heatmap_returns(monkeypatch, None)
    _patch_ranker_returns(monkeypatch, _two_clips())

    r = select_one_video(
        repo=repo, cfg=cfg, video_id="v1",
        whisper_model_loader=runner_mod._make_whisper_loader(cfg),
        retranscribe=True,
    )
    assert r.outcome == SelectorOutcome.selected
    assert invoked["n"] == 1
    # Cache rewritten with fresh segments (10 of them, not the 1-seg stale cache).
    new_cache = json.loads((transcripts_dir / "v1.json").read_text())
    assert len(new_cache["segments"]) == 10


def test_force_preserves_downstream_columns(tmp_path, monkeypatch):
    """Critical: --force re-rank must NOT clobber publish_at_utc / output_path."""
    cfg, repo = _setup(tmp_path, status="selected")
    # Seed an existing clip + downstream metadata.
    repo.upsert_selector_clip(
        clip_id="v1_0_30", video_id="v1", start_s=0.0, end_s=30.0,
        hook="old hook", suggested_title="Old Title", selection_method="transcript_only",
    )
    repo.conn.execute(
        "UPDATE clips SET publish_at_utc='2026-05-15T09:00:00Z', "
        "output_path='output/pending/x.mp4', youtube_video_id='ytid' WHERE clip_id='v1_0_30'"
    )
    # Pre-populate cache so Whisper isn't needed.
    transcripts_dir = Path(cfg.paths.transcripts_dir)
    cached = transcriber_mod.Transcript(
        video_id="v1", model="large-v3", compute_type="int8_float16",
        duration_seconds=100.0, language="en", language_probability=0.99,
        segments=[
            {"start": i * 10.0, "end": (i + 1) * 10.0, "text": f"seg{i}", "words": []}
            for i in range(10)
        ],
    )
    transcriber_mod.atomic_write(transcripts_dir, cached)

    _patch_whisper(monkeypatch, TripwireWhisperModel)
    _patch_heatmap_returns(monkeypatch, None)
    # Ranker picks c0 (same range as the seeded v1_0_30) but with new hook/title.
    _patch_ranker_returns(monkeypatch, [
        ranker_mod.RankedClip(candidate_id="c0", hook="new hook", suggested_title="New Title", score=9.0),
        ranker_mod.RankedClip(candidate_id="c1", hook="other", suggested_title="Other", score=8.0),
    ])

    select_one_video(
        repo=repo, cfg=cfg, video_id="v1",
        whisper_model_loader=runner_mod._make_whisper_loader(cfg),
        force=True,
    )

    row = repo.conn.execute("SELECT * FROM clips WHERE clip_id='v1_0_30'").fetchone()
    # Selector columns updated.
    assert row["hook"] == "new hook"
    assert row["suggested_title"] == "New Title"
    # Downstream columns preserved.
    assert row["publish_at_utc"] == "2026-05-15T09:00:00Z"
    assert row["output_path"] == "output/pending/x.mp4"
    assert row["youtube_video_id"] == "ytid"


# ---- Atomic transcript ------------------------------------------------------


def test_whisper_failure_leaves_lang_ok_no_cache(tmp_path, monkeypatch):
    """Critical: mid-iteration Whisper failure → no .json or .json.tmp on disk, status unchanged."""
    cfg, repo = _setup(tmp_path)
    _patch_whisper(monkeypatch, TranscribeRaisesModel)
    _patch_heatmap_returns(monkeypatch, None)
    _patch_ranker_returns(monkeypatch, _two_clips())

    r = select_one_video(
        repo=repo, cfg=cfg, video_id="v1",
        whisper_model_loader=runner_mod._make_whisper_loader(cfg),
    )
    assert r.outcome == SelectorOutcome.error_transcribe
    assert "CUDA OOM" in (r.reason or "")
    assert repo.get_video("v1")["status"] == "lang_ok"
    transcripts_dir = Path(cfg.paths.transcripts_dir)
    assert not (transcripts_dir / "v1.json").exists()
    assert not (transcripts_dir / "v1.json.tmp").exists()


def test_missing_raw_file_skips(tmp_path, monkeypatch):
    cfg = _make_cfg_with_paths(tmp_path)
    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn); repo = Repository(conn)
    _seed_video(repo, "v1")  # status=lang_ok, no file
    _patch_whisper(monkeypatch, TripwireWhisperModel)

    r = select_one_video(
        repo=repo, cfg=cfg, video_id="v1",
        whisper_model_loader=runner_mod._make_whisper_loader(cfg),
    )
    assert r.outcome == SelectorOutcome.skipped_missing_file
    assert repo.get_video("v1")["status"] == "lang_ok"


# ---- Heatmap behavior ------------------------------------------------------


def test_heatmap_hit_marks_selection_method(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    _patch_whisper(monkeypatch, StubWhisperModel)
    # Heat marker at 5s puts c0 (which covers 0-30) into heatmap_aided territory.
    from src.selector.windows import HeatMarker
    _patch_heatmap_returns(monkeypatch, [HeatMarker(start_s=5.0, duration_s=2.0, intensity=0.99)])
    _patch_ranker_returns(monkeypatch, _two_clips())

    r = select_one_video(
        repo=repo, cfg=cfg, video_id="v1",
        whisper_model_loader=runner_mod._make_whisper_loader(cfg),
    )
    assert r.outcome == SelectorOutcome.selected
    assert r.heatmap_fetched is True
    methods = {row["selection_method"] for row in repo.conn.execute(
        "SELECT selection_method FROM clips WHERE video_id='v1'").fetchall()}
    assert "heatmap_aided" in methods


def test_heatmap_miss_uses_transcript_only(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    _patch_whisper(monkeypatch, StubWhisperModel)
    _patch_heatmap_returns(monkeypatch, None)  # fail-open None
    _patch_ranker_returns(monkeypatch, _two_clips())

    r = select_one_video(
        repo=repo, cfg=cfg, video_id="v1",
        whisper_model_loader=runner_mod._make_whisper_loader(cfg),
    )
    assert r.outcome == SelectorOutcome.selected
    assert r.heatmap_fetched is False
    methods = {row["selection_method"] for row in repo.conn.execute(
        "SELECT selection_method FROM clips WHERE video_id='v1'").fetchall()}
    assert methods == {"transcript_only"}


def test_run_all_low_hit_rate_emits_alert(tmp_path, monkeypatch):
    cfg = _make_cfg_with_paths(tmp_path)
    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn); repo = Repository(conn)
    for i in range(5):
        vid = f"v{i}"
        _seed_video(repo, vid)
        _touch_raw(cfg, vid)

    _patch_whisper(monkeypatch, StubWhisperModel)
    _patch_heatmap_returns(monkeypatch, None)  # all miss
    _patch_ranker_returns(monkeypatch, _two_clips())

    run_all(repo, cfg)

    alerts_path = Path(cfg.paths.logs_dir) / "alerts.md"
    assert alerts_path.exists()
    text = alerts_path.read_text()
    assert "heatmap_low_hit_rate" in text


# ---- Ranker error handling -------------------------------------------------


def test_rank_failure_leaves_transcribed(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    _patch_whisper(monkeypatch, StubWhisperModel)
    _patch_heatmap_returns(monkeypatch, None)
    _patch_ranker_returns(monkeypatch, ranker_mod.RankerError("ollama down"))

    r = select_one_video(
        repo=repo, cfg=cfg, video_id="v1",
        whisper_model_loader=runner_mod._make_whisper_loader(cfg),
    )
    assert r.outcome == SelectorOutcome.error_rank
    assert repo.get_video("v1")["status"] == "transcribed"
    assert (Path(cfg.paths.transcripts_dir) / "v1.json").exists()


def test_run_all_rank_errors_alert(tmp_path, monkeypatch):
    cfg = _make_cfg_with_paths(tmp_path)
    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn); repo = Repository(conn)
    _seed_video(repo, "v1"); _touch_raw(cfg, "v1")

    _patch_whisper(monkeypatch, StubWhisperModel)
    _patch_heatmap_returns(monkeypatch, [])
    _patch_ranker_returns(monkeypatch, ranker_mod.RankerError("ollama down"))

    run_all(repo, cfg)

    text = (Path(cfg.paths.logs_dir) / "alerts.md").read_text()
    assert "selector_rank_errors" in text


# ---- Empty / model-load tripwires ------------------------------------------


def test_run_all_empty_does_not_load_whisper(tmp_path, monkeypatch):
    cfg = _make_cfg_with_paths(tmp_path)
    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn); repo = Repository(conn)
    _patch_whisper(monkeypatch, TripwireWhisperModel)

    results = run_all(repo, cfg)
    assert results == []


def test_run_all_model_load_failure_raises(tmp_path, monkeypatch):
    cfg = _make_cfg_with_paths(tmp_path)
    db = Path(cfg.paths.state_db)
    conn = connect(db); initialize_schema(conn); repo = Repository(conn)
    _seed_video(repo, "v1"); _touch_raw(cfg, "v1")

    _patch_whisper(monkeypatch, RaisingCtorWhisperModel)
    _patch_heatmap_returns(monkeypatch, None)

    with pytest.raises(SelectorModelLoadError, match="missing cuDNN"):
        run_all(repo, cfg)
    assert repo.get_video("v1")["status"] == "lang_ok"


# ---- Dry-run ---------------------------------------------------------------


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    _patch_whisper(monkeypatch, StubWhisperModel)
    _patch_heatmap_returns(monkeypatch, None)
    _patch_ranker_returns(monkeypatch, _two_clips())

    before_status = repo.get_video("v1")["status"]
    r = select_one_video(
        repo=repo, cfg=cfg, video_id="v1",
        whisper_model_loader=runner_mod._make_whisper_loader(cfg),
        dry_run=True,
    )
    assert r.outcome == SelectorOutcome.selected
    assert repo.get_video("v1")["status"] == before_status  # unchanged
    clips = repo.conn.execute("SELECT * FROM clips WHERE video_id='v1'").fetchall()
    assert len(clips) == 0
    assert not (Path(cfg.paths.transcripts_dir) / "v1.json").exists()


# ---- No-windows path -------------------------------------------------------


def test_video_too_short_yields_no_windows(tmp_path, monkeypatch):
    cfg, repo = _setup(tmp_path)
    short_segments = [_stub_segment(0.0, 5.0, "tiny", [_stub_word(0.0, 1.0, "tiny")])]

    class ShortModel(StubWhisperModel):
        def __init__(self, *a, **kw):
            super().__init__(*a, segments=short_segments, **kw)

    _patch_whisper(monkeypatch, ShortModel)
    _patch_heatmap_returns(monkeypatch, None)
    _patch_ranker_returns(monkeypatch, _two_clips())  # shouldn't be called

    r = select_one_video(
        repo=repo, cfg=cfg, video_id="v1",
        whisper_model_loader=runner_mod._make_whisper_loader(cfg),
    )
    assert r.outcome == SelectorOutcome.error_no_windows
    assert repo.get_video("v1")["status"] == "transcribed"
