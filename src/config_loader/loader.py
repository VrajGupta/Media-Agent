from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Pivot.6 sub-models
# ---------------------------------------------------------------------------


class AiGenConfig(BaseModel):
    model: str = "kwaivgi/kling-v3.0-std"
    per_clip_cost_cents_max: int
    daily_spend_cents_ceiling: int
    max_concurrent: int = 2
    shots_per_clip_min: int = 4
    shots_per_clip_max: int = 6
    shot_duration_s: int = 5
    style_suffix: str = (
        "3D animated, Pixar-shaded surface, surreal cinematic lighting, "
        "vertical 9:16, photoreal textures with stylized characters, dark moody atmosphere"
    )


class ScripterConfig(BaseModel):
    topic_pool: list[str]
    target_word_count: int = 80
    max_retries: int = 3


class NarrationConfig(BaseModel):
    voice: str = "en-US-GuyNeural"
    rate: str = "-8%"
    pitch: str = "-2Hz"


class SubtitlesConfig(BaseModel):
    position_x: int = 540
    position_y: int = 1500
    font_size: int = 52
    font_name: str = "Arial"


class ComplianceConfig(BaseModel):
    ai_disclosure: bool = True


# ---------------------------------------------------------------------------
# Core sub-models (retained from previous phases)
# ---------------------------------------------------------------------------


class Retention(BaseModel):
    # Pivot.6 TTLs
    ai_gen_shots: int = 7
    narration: int = 14
    scripts: int = 90
    # Retained
    output_post_upload: int
    rejected_clips: int
    dup_hashes: int
    quota_usage: int
    vacuum_every_days: int


class Paths(BaseModel):
    state_db: str
    pending_dir: str
    approved_dir: str
    rejected_dir: str
    dry_run_dir: str
    orphans_dir: str = "output/orphans"
    logs_dir: str
    oauth_token: str
    client_secrets: str
    # Retained with defaults so older config.yaml files keep working
    raw_dir: str = "data/raw"
    transcripts_dir: str = "data/transcripts"
    music_dir: str = "data/music"
    # Pivot.6 dirs
    ai_gen_shots_dir: str = "data/ai_gen_shots"
    narration_dir: str = "data/narration"
    scripts_dir: str = "data/scripts"


# ---------------------------------------------------------------------------
# Top-level Config (Pivot.6)
# ---------------------------------------------------------------------------


class Config(BaseModel):
    # Cadence
    clips_per_day: int
    days_per_run: int
    upload_slots: list[str]
    timezone: str

    # Models
    whisper_model: str
    whisper_compute_type: str
    whisper_device: str
    ollama_model: str

    # Policy gate
    human_review: bool
    banlist: list[str]
    hook_sanity_min_score: int
    profanity_max_score: int

    # Quality screen
    min_speech_density: float = 1.5
    min_word_confidence: float = 0.6
    dedup_lookback_days: int
    phash_min_hamming: int

    # Assembler / render
    output_resolution: list[int]
    nvenc_preset: str
    nvenc_cq: int
    loudness_target_lufs: float
    music_enabled: bool = True
    music_volume_db: float = -15.0

    # Quota
    youtube_quota_daily_units: int
    youtube_quota_ceiling_units: int
    videos_insert_unit_cost: int

    # Pivot.6 sub-models
    ai_gen: AiGenConfig
    scripter: ScripterConfig
    narration: NarrationConfig
    subtitles: SubtitlesConfig = Field(default_factory=SubtitlesConfig)
    compliance: ComplianceConfig = Field(default_factory=ComplianceConfig)

    # Nested
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
