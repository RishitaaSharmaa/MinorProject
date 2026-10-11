"""API-key guard for machine-to-machine endpoints such as event ingest."""

import hmac

from fastapi import Header, HTTPException

from app.config import get_settings


def require_ingest_key(x_api_key: str | None = Header(default=None)) -> None:
    """Reject requests that do not carry the configured ingest API key."""
    expected = get_settings().ingest_api_key.get_secret_value()
    if not expected:
        raise HTTPException(status_code=503, detail="Event ingest is disabled: INGEST_API_KEY is not set")
    if x_api_key is None or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
