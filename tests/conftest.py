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

    class _Paths:
        def __init__(self, raw_dir: str, logs_dir: str, state_db: str,
                     transcripts_dir: str = "", pending_dir: str = ""):
            self.raw_dir = raw_dir
            self.logs_dir = logs_dir
            self.state_db = state_db
            self.transcripts_dir = transcripts_dir
            self.pending_dir = pending_dir

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
        from pathlib import Path
        self.project_root = Path(tmp_path)
        raw = tmp_path / "raw"
        logs = tmp_path / "logs"
        transcripts = tmp_path / "transcripts"
        pending = tmp_path / "output" / "pending"
        for d in (raw, logs, transcripts, pending):
            d.mkdir(parents=True, exist_ok=True)
        self.paths = self._Paths(
            str(raw), str(logs), str(tmp_path / "state.db"),
            transcripts_dir=str(transcripts),
            pending_dir=str(pending),
        )

    def abs_path(self, rel: str):
        from pathlib import Path
        p = Path(rel)
        return p if p.is_absolute() else (Path.cwd() / p)
