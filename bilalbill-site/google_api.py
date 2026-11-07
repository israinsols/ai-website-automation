"""Authentication helpers for optional Google Search Console API access."""

from __future__ import annotations

import json
import os

from google.auth.transport.requests import Request
from google.oauth2 import service_account

SCOPE = "https://www.googleapis.com/auth/webmasters"


def access_token() -> str:
    """Create a short-lived access token from JSON stored only in an environment secret."""
    raw = os.getenv("GSC_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GSC_SERVICE_ACCOUNT_JSON is missing.")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("GSC_SERVICE_ACCOUNT_JSON must contain valid JSON.") from exc
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=[SCOPE]
    )
    credentials.refresh(Request())
    if not credentials.token:
        raise RuntimeError("Google authentication did not return an access token.")
    return credentials.token
