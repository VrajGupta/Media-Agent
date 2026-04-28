"""Shared YouTube Data API v3 client builder.

Lives outside `discovery/` and `uploader/` so both can depend on it without
depending on each other. Loads the cached refresh token written by
`scripts/oauth_first_run.py` (which requests both youtube.upload and
youtube.readonly scopes).
"""

from __future__ import annotations

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build


def _load_credentials(token_path: Path) -> Credentials:
    payload = json.loads(token_path.read_text())
    creds = Credentials(
        token=payload.get("token"),
        refresh_token=payload.get("refresh_token"),
        token_uri=payload.get("token_uri"),
        client_id=payload.get("client_id"),
        client_secret=payload.get("client_secret"),
        scopes=payload.get("scopes"),
    )
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(
            json.dumps(
                {
                    "token": creds.token,
                    "refresh_token": creds.refresh_token,
                    "token_uri": creds.token_uri,
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "scopes": creds.scopes,
                },
                indent=2,
            )
        )
    return creds


def build_youtube_client(cfg) -> Resource:
    token_path = cfg.abs_path(cfg.paths.oauth_token)
    if not token_path.exists():
        raise FileNotFoundError(
            f"OAuth token not found at {token_path}. "
            "Run `python scripts/oauth_first_run.py` once to create it."
        )
    creds = _load_credentials(token_path)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)
