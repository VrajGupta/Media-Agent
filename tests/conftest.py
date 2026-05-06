"""Shared pytest fixtures and helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import httplib2
from googleapiclient.errors import HttpError

# Make `src.*` importable when running `pytest` from the repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def make_http_error(status: int, reason: str = "Server Error") -> HttpError:
    """Construct a googleapiclient HttpError with a given status code.

    HttpError's constructor wants an httplib2 Response (dict-like with 'status')
    and bytes content. This helper hides the awkward setup.
    """
    resp = httplib2.Response({"status": status, "reason": reason})
    resp.reason = reason  # httplib2.Response stores reason as attr too
    content = ('{"error":{"code":' + str(status) + ',"message":"' + reason + '"}}').encode()
    return HttpError(resp, content)


class FakeRequest:
    """Mimics googleapiclient's request object: only `.execute()` matters."""

    def __init__(self, *, raises: Exception | None = None, response: dict | None = None):
        self._raises = raises
        self._response = response

    def execute(self):
        if self._raises is not None:
            raise self._raises
        return self._response or {}


class StubConfig:
    """Minimal duck-typed Config for downloader tests.

    Avoids round-tripping through pydantic + yaml so each test can dial in
    the exact knobs it needs.
    """

    class _Retention:
        def __init__(
            self,
            *,
            raw_video: int = 14,
            transcript: int = 90,
            output_post_upload: int = 7,
            rejected_clips: int = 30,
            dup_hashes: int = 90,
            quota_usage: int = 90,
            vacuum_every_days: int = 30,
        ):
            self.raw_video = raw_video
            self.transcript = transcript
            self.output_post_upload = output_post_upload
            self.rejected_clips = rejected_clips
            self.dup_hashes = dup_hashes
            self.quota_usage = quota_usage
            self.vacuum_every_days = vacuum_every_days

    class _Paths:
        def __init__(self, raw_dir: str, logs_dir: str, state_db: str,
                     transcripts_dir: str = "", pending_dir: str = "",
                     rejected_dir: str = "",
                     # Phase 5
                     approved_dir: str = "", dry_run_dir: str = "",
                     orphans_dir: str = "", oauth_token: str = ""):
            self.raw_dir = raw_dir
            self.logs_dir = logs_dir
            self.state_db = state_db
            self.transcripts_dir = transcripts_dir
            self.pending_dir = pending_dir
            self.rejected_dir = rejected_dir
            # Phase 5
            self.approved_dir = approved_dir
            self.dry_run_dir = dry_run_dir
            self.orphans_dir = orphans_dir
            self.oauth_token = oauth_token

    def __init__(
        self,
        tmp_path,
        *,
        soft_cap_gb: int = 50,
        hard_cap_gb: int = 100,
        free_floor_gb: int = 5,
        min_height: int = 720,
        max_height: int = 1080,
        estimated_bytes: int = 524288000,
        whisper_model: str = "large-v3",
        whisper_device: str = "cuda",
        whisper_compute_type: str = "int8_float16",
        lang_detect_threshold: float = 0.7,
        lang_detect_target_lang: str = "en",
        selector_max_candidates: int = 25,
        nvenc_preset: str = "p5",
        nvenc_cq: int = 23,
        loudness_target_lufs: float = -14.0,
        gameplay_pool: list[str] | None = None,
        # Phase 4.5 — policy_gate / quality_screen knobs.
        banlist: list[str] | None = None,
        hook_sanity_min_score: int = 3,
        profanity_max_score: int = 5,
        min_speech_density: float = 1.5,
        min_word_confidence: float = 0.6,
        dedup_lookback_days: int = 90,
        phash_min_hamming: int = 8,
        ollama_model: str = "qwen2.5:3b-instruct",
        # Phase 5 — uploader knobs.
        videos_insert_unit_cost: int = 1600,
        youtube_quota_ceiling_units: int = 9000,
        # Phase 6 — slot_planner / daily_upload knobs.
        clips_per_day: int = 4,
        days_per_run: int = 7,
        upload_slots: list[str] | None = None,
        timezone: str = "Asia/Singapore",
        human_review: bool = True,
    ):
        self.disk_soft_cap_gb = soft_cap_gb
        self.disk_hard_cap_gb = hard_cap_gb
        self.free_disk_safety_floor_gb = free_floor_gb
        self.download_min_height = min_height
        self.download_max_height = max_height
        self.download_estimated_bytes_per_video = estimated_bytes
        self.whisper_model = whisper_model
        self.whisper_device = whisper_device
        self.whisper_compute_type = whisper_compute_type
        self.lang_detect_threshold = lang_detect_threshold
        self.lang_detect_target_lang = lang_detect_target_lang
        self.selector_max_candidates = selector_max_candidates
        self.nvenc_preset = nvenc_preset
        self.nvenc_cq = nvenc_cq
        self.loudness_target_lufs = loudness_target_lufs
        self.gameplay_pool = gameplay_pool if gameplay_pool is not None else []
        # Phase 4.5
        self.banlist = banlist if banlist is not None else []
        self.hook_sanity_min_score = hook_sanity_min_score
        self.profanity_max_score = profanity_max_score
        self.min_speech_density = min_speech_density
        self.min_word_confidence = min_word_confidence
        self.dedup_lookback_days = dedup_lookback_days
        self.phash_min_hamming = phash_min_hamming
        self.ollama_model = ollama_model
        # Phase 5
        self.videos_insert_unit_cost = videos_insert_unit_cost
        self.youtube_quota_ceiling_units = youtube_quota_ceiling_units
        # Phase 6
        self.clips_per_day = clips_per_day
        self.days_per_run = days_per_run
        self.upload_slots = upload_slots if upload_slots is not None else [
            "09:00", "13:00", "17:00", "21:00",
        ]
        self.timezone = timezone
        self.human_review = human_review
        self.retention = self._Retention()
        from pathlib import Path
        self.project_root = Path(tmp_path)
        raw = tmp_path / "raw"
        logs = tmp_path / "logs"
        transcripts = tmp_path / "transcripts"
        pending = tmp_path / "output" / "pending"
        rejected = tmp_path / "output" / "rejected"
        # Phase 5
        approved = tmp_path / "output" / "approved"
        dry_run = tmp_path / "output" / "dry_run"
        orphans = tmp_path / "output" / "orphans"
        for d in (raw, logs, transcripts, pending, rejected,
                  approved, dry_run, orphans):
            d.mkdir(parents=True, exist_ok=True)
        self.paths = self._Paths(
            str(raw), str(logs), str(tmp_path / "state.db"),
            transcripts_dir=str(transcripts),
            pending_dir=str(pending),
            rejected_dir=str(rejected),
            approved_dir=str(approved),
            dry_run_dir=str(dry_run),
            orphans_dir=str(orphans),
            oauth_token=str(tmp_path / "oauth_token.json"),
        )

    def abs_path(self, rel: str):
        from pathlib import Path
        p = Path(rel)
        return p if p.is_absolute() else (Path.cwd() / p)
