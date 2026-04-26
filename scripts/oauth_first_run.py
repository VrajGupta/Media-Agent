"""
First-time YouTube OAuth flow.

Reads data/client_secret.json, opens a browser, prompts the user to grant
access on the channel's Google account, and writes the cached refresh token
to data/oauth_token.json.

After this runs once, all uploads happen non-interactively.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    client_secrets = repo_root / "data" / "client_secret.json"
    token_path = repo_root / "data" / "oauth_token.json"

    if not client_secrets.exists():
        print(f"ERROR: {client_secrets} not found.")
        return 1

    if token_path.exists():
        print(f"Existing token at {token_path}. Delete it first if you want to re-auth.")
        return 0

    print(f"Using client secrets: {client_secrets}", flush=True)
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
    print("\n=== OPEN THIS URL IN YOUR BROWSER ===", flush=True)
    print("(sign in with the Google account that owns the YouTube channel)\n", flush=True)
    creds = flow.run_local_server(
        port=0,
        prompt="consent",
        access_type="offline",
        open_browser=False,
        authorization_prompt_message="{url}",
    )

    token_payload = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }
    token_path.write_text(json.dumps(token_payload, indent=2))
    print(f"\nOK — refresh token cached to {token_path}")
    if not creds.refresh_token:
        print("WARNING: no refresh_token returned. You may need to revoke the app at "
              "https://myaccount.google.com/permissions and re-run.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
