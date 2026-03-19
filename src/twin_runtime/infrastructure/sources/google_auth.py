"""Shared Google OAuth2 helper for Gmail and Calendar adapters.

Setup:
1. Go to https://console.cloud.google.com
2. Create a project (or use existing)
3. Enable Gmail API and Google Calendar API
4. Create OAuth 2.0 credentials (Desktop app)
5. Download credentials.json
6. Place it at ~/.twin-runtime/google_credentials.json

First run will open a browser for consent. Token is cached at
~/.twin-runtime/google_token.json for subsequent runs.
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import List, Optional

# Scopes needed for Gmail read + Calendar read
GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
CALENDAR_READONLY = "https://www.googleapis.com/auth/calendar.readonly"
ALL_SCOPES = [GMAIL_READONLY, CALENDAR_READONLY]

_CONFIG_DIR = Path.home() / ".twin-runtime"
_CREDENTIALS_PATH = _CONFIG_DIR / "google_credentials.json"
_TOKEN_PATH = _CONFIG_DIR / "google_token.json"


def get_google_credentials(
    scopes: Optional[List[str]] = None,
    credentials_path: Optional[str] = None,
    token_path: Optional[str] = None,
):
    """Get authenticated Google credentials.

    Returns a google.oauth2.credentials.Credentials object.
    Handles token refresh and initial OAuth flow.
    """
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    scopes = scopes or ALL_SCOPES
    creds_file = Path(credentials_path) if credentials_path else _CREDENTIALS_PATH
    tok_file = Path(token_path) if token_path else _TOKEN_PATH

    creds = None

    # Try loading cached token
    if tok_file.exists():
        creds = Credentials.from_authorized_user_file(str(tok_file), scopes)

    # Refresh or get new token
    if creds and creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
    elif not creds or not creds.valid:
        if not creds_file.exists():
            raise FileNotFoundError(
                f"Google credentials not found at {creds_file}.\n"
                f"Download OAuth credentials from Google Cloud Console and save to:\n"
                f"  {creds_file}\n"
                f"See: https://console.cloud.google.com/apis/credentials"
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), scopes)
        creds = flow.run_local_server(port=0)

    # Cache token with restricted permissions
    tok_file.parent.mkdir(parents=True, exist_ok=True)
    tok_file.write_text(creds.to_json())
    os.chmod(str(tok_file), 0o600)

    return creds


def check_google_auth(credentials_path: Optional[str] = None) -> bool:
    """Check if Google credentials are available (not necessarily valid)."""
    creds_file = Path(credentials_path) if credentials_path else _CREDENTIALS_PATH
    tok_file = _TOKEN_PATH
    return creds_file.exists() or tok_file.exists()
