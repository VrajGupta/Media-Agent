from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, Field


class Retention(BaseModel):
    raw_video: int
    transcript: int
    output_post_upload: int
    rejected_clips: int
    dup_hashes: int
    quota_usage: int
    vacuum_every_days: int


class Paths(BaseModel):
    state_db: str
    raw_dir: str
    transcripts_dir: str
    pending_dir: str
    approved_dir: str
    rejected_dir: str
    dry_run_dir: str
    orphans_dir: str = "output/orphans"   # Phase 5; default for backward compat with older config files
    logs_dir: str
    oauth_token: str
    client_secrets: str


class Config(BaseModel):
    clips_per_day: int
    days_per_run: int
    upload_slots: list[str]

    timezone: str

    keywords: list[str]
    search_max_results_per_keyword: int
    discovery_max_inspected_per_keyword: int = 100
    discovery_min_interval_hours: int = 6
    min_source_duration_seconds: int
    recency_window_days: int
    virality_score_threshold: float

    whisper_model: str
    whisper_compute_type: str
    whisper_device: str
    ollama_model: str

    lang_detect_threshold: float = 0.7
    lang_detect_target_lang: str = "en"

    clip_min_seconds: int
    clip_max_seconds: int
    clips_per_video: int
    selector_max_candidates: int = 25

    # Captions (Pivot.1) — caption-first transcript path
    caption_min_confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    caption_prefer_manual: bool = True

    human_review: bool
    banlist: list[str]
    hook_sanity_min_score: int
    profanity_max_score: int

    min_speech_density: float
    min_word_confidence: float
    dedup_lookback_days: int
    phash_min_hamming: int

    disk_soft_cap_gb: int = 50
    disk_hard_cap_gb: int = 100
    free_disk_safety_floor_gb: int = 5
    download_min_height: int = 720
    download_max_height: int = 1080
    download_estimated_bytes_per_video: int = 524288000

    # Render (Pivot.3) — full-screen blurred-bg replaces split-screen.
    # top_pane_height / bottom_pane_height / gameplay_pool removed; older
    # config.yaml files with those fields will be silently ignored by pydantic
    # (they're not declared here), letting the user edit at their pace.
    output_resolution: list[int]
    render_strategy: Literal["blurred_bg", "center_crop", "letterbox"] = "blurred_bg"
    blurred_bg_sigma: int = Field(default=20, ge=0, le=100)
    source_pane_aspect: str = "16:9"
    nvenc_preset: str
    nvenc_cq: int
    loudness_target_lufs: float

    # Copyright acknowledgement (Pivot.0) — optional string the user sets to
    # acknowledge the elevated strike risk of the movie-clip pivot. Surfaced
    # as a WARN in bootstrap --check; not a hard gate.
    copyright_acknowledgement: Optional[str] = None

    youtube_quota_daily_units: int
    youtube_quota_ceiling_units: int
    videos_insert_unit_cost: int
    search_list_unit_cost: int
    videos_list_unit_cost: int

    retention: Retention
    paths: Paths

    project_root: Path = Field(default_factory=Path.cwd, exclude=True)

    def abs_path(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (self.project_root / p)


def load_config(path: str | Path = "config.yaml") -> Config:
    cfg_path = Path(path).resolve()
    with cfg_path.open("r") as f:
        raw: dict[str, Any] = yaml.safe_load(f)
    cfg = Config(**raw)
    cfg.project_root = cfg_path.parent
    return cfg
