"""OpenRouter Kling 3.0 text-to-video provider.

API: https://openrouter.ai/api/v1/videos
Auth: Bearer {OPENROUTER_API_KEY}
Model: kwaivgi/kling-v3.0-std (or kwaivgi/kling-v3.0-pro)

Workflow:
  submit  → POST /api/v1/videos          → returns job id
  poll    → GET  /api/v1/videos/{id}      → returns status + unsigned_urls
  download→ GET  unsigned_urls[0]         → streams mp4

Status mapping (OpenRouter → GenerationStatus):
  pending     → QUEUED
  in_progress → RUNNING
  completed   → SUCCEEDED
  failed      → FAILED
"""

from __future__ import annotations

import os
from pathlib import Path

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .base import GenerationStatus, Provider, ShotResult

_BASE_URL = "https://openrouter.ai/api/v1"

_STATUS_MAP: dict[str, GenerationStatus] = {
    "pending": GenerationStatus.QUEUED,
    "in_progress": GenerationStatus.RUNNING,
    "completed": GenerationStatus.SUCCEEDED,
    "failed": GenerationStatus.FAILED,
}


class OpenRouterKlingClient(Provider):
    provider_name = "kling"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = "kwaivgi/kling-v3.0-std",
        session: requests.Session | None = None,
    ) -> None:
        self._api_key = api_key or os.environ["OPENROUTER_API_KEY"]
        self.model = model
        self._session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Provider interface
    # ------------------------------------------------------------------

    def submit(
        self,
        prompt: str,
        *,
        duration_s: int = 5,
        aspect_ratio: str = "9:16",
    ) -> str:
        """Submit a text-to-video job. Returns OpenRouter job id."""
        body = {
            "model": self.model,
            "prompt": prompt,
            "duration": duration_s,
            "aspect_ratio": aspect_ratio,
            "enable_audio": False,
        }
        response = self._post_with_retry("/videos", body)
        job_id = response.get("id")
        if not job_id:
            raise ValueError(f"OpenRouter submit: no id in response: {response}")
        return job_id

    def poll(self, external_id: str) -> ShotResult:
        """Query job status. Returns ShotResult with current state."""
        response = self._get_with_retry(f"/videos/{external_id}")
        return self._parse_response(external_id, response)

    def download(self, url: str, dest: Path) -> Path:
        """Stream download video to dest path. Returns dest."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        headers = self._headers() if "openrouter.ai" in url else {}
        resp = self._session.get(url, headers=headers, stream=True, timeout=120)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        return dest

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_response(self, external_id: str, response: dict) -> ShotResult:
        raw_status = response.get("status", "pending")
        status = _STATUS_MAP.get(raw_status, GenerationStatus.QUEUED)

        download_url: str | None = None
        if status == GenerationStatus.SUCCEEDED:
            urls = response.get("unsigned_urls") or []
            if urls:
                download_url = urls[0]

        error: str | None = None
        if status == GenerationStatus.FAILED:
            error = response.get("error") or "unknown error"

        cost_cents: int | None = None
        usage = response.get("usage") or {}
        if usage.get("cost"):
            cost_cents = int(usage["cost"] * 100)

        return ShotResult(
            external_id=external_id,
            status=status,
            download_url=download_url,
            cost_cents=cost_cents,
            error=error,
            raw=response,
        )

    @retry(
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
        wait=wait_exponential(min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _post_with_retry(self, path: str, body: dict) -> dict:
        resp = self._session.post(
            _BASE_URL + path,
            json=body,
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    @retry(
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
        wait=wait_exponential(min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _get_with_retry(self, path: str) -> dict:
        resp = self._session.get(
            _BASE_URL + path,
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
