"""Kling AI text-to-video provider.

API: https://api-singapore.klingai.com
Auth: JWT (HS256) with {iss: access_key, exp: now+1800, nbf: now-5}
Docs: https://app.klingai.com/global/dev/document-api/

Status mapping (Kling → GenerationStatus):
  submitted  → QUEUED
  processing → RUNNING
  succeed    → SUCCEEDED
  failed     → FAILED
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import jwt
import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .base import GenerationStatus, Provider, ShotResult

_BASE_URL = "https://api-singapore.klingai.com"
_TOKEN_TTL = 1800       # 30 min
_TOKEN_REFRESH = 300    # refresh when <5 min left

_STATUS_MAP = {
    "submitted": GenerationStatus.QUEUED,
    "processing": GenerationStatus.RUNNING,
    "succeed": GenerationStatus.SUCCEEDED,
    "failed": GenerationStatus.FAILED,
}


class KlingClient(Provider):
    provider_name = "kling"

    def __init__(
        self,
        access_key: str | None = None,
        secret_key: str | None = None,
        *,
        model_name: str = "kling-v1-6",
        mode: str = "std",
        cfg_scale: float = 0.5,
        session: requests.Session | None = None,
    ) -> None:
        self._access_key = access_key or os.environ["KLING_ACCESS_KEY"]
        self._secret_key = secret_key or os.environ["KLING_SECRET_KEY"]
        self.model_name = model_name
        self.mode = mode
        self.cfg_scale = cfg_scale
        self._session = session or requests.Session()
        self._token: str | None = None
        self._token_exp: float = 0.0

    # ------------------------------------------------------------------
    # JWT auth helpers
    # ------------------------------------------------------------------

    def _make_token(self) -> str:
        now = int(time.time())
        payload = {
            "iss": self._access_key,
            "exp": now + _TOKEN_TTL,
            "nbf": now - 5,
        }
        return jwt.encode(payload, self._secret_key, algorithm="HS256")

    def _get_token(self) -> str:
        """Return a cached token, refreshing if it's within 5 min of expiry."""
        if time.time() >= self._token_exp - _TOKEN_REFRESH or self._token is None:
            self._token = self._make_token()
            self._token_exp = time.time() + _TOKEN_TTL
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
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
        """Submit a text-to-video job. Returns external_id (Kling task_id)."""
        body = {
            "model_name": self.model_name,
            "prompt": prompt,
            "mode": self.mode,
            "duration": str(duration_s),
            "aspect_ratio": aspect_ratio,
            "cfg_scale": self.cfg_scale,
        }
        response = self._post_with_retry("/v1/videos/text2video", body)
        data = response.get("data", {})
        task_id = data.get("task_id")
        if not task_id:
            raise ValueError(f"Kling submit: no task_id in response: {response}")
        return task_id

    def poll(self, external_id: str) -> ShotResult:
        """Query task status. Returns ShotResult with current state."""
        response = self._get_with_retry(f"/v1/videos/text2video/{external_id}")
        return self._parse_response(external_id, response)

    def download(self, url: str, dest: Path) -> Path:
        """Stream download video to dest path. Returns dest."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        resp = self._session.get(url, stream=True, timeout=120)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        return dest

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_response(self, external_id: str, response: dict) -> ShotResult:
        data = response.get("data", {})
        raw_status = data.get("task_status", "")
        status = _STATUS_MAP.get(raw_status, GenerationStatus.QUEUED)

        download_url: str | None = None
        if status == GenerationStatus.SUCCEEDED:
            videos = (data.get("task_result") or {}).get("videos", [])
            if videos:
                download_url = videos[0].get("url")

        error: str | None = None
        if status == GenerationStatus.FAILED:
            error = data.get("task_status_msg") or "unknown error"

        return ShotResult(
            external_id=external_id,
            status=status,
            download_url=download_url,
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
