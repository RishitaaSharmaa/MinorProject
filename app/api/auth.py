"""API-key guards for machine-to-machine and operator endpoints."""

import hmac

from fastapi import Header, HTTPException

from app.config import get_settings


def require_admin_key(x_api_key: str | None = Header(default=None)) -> None:
    """Accept only the operator's global key (never a customer workspace key)."""
    expected = get_settings().ingest_api_key.get_secret_value()
    if get_settings().agent_mode:
        raise HTTPException(status_code=404, detail="Not found")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin access is disabled: INGEST_API_KEY is not set")
    if x_api_key is None or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def require_ingest_key(x_api_key: str | None = Header(default=None)) -> None:
    """Accept the global ingest key, or this agent's token when running as an agent."""
    settings = get_settings()
    expected = settings.ingest_api_key.get_secret_value()
    if expected and x_api_key is not None and hmac.compare_digest(x_api_key, expected):
        return
    agent_token = settings.agent_token.get_secret_value()
    if settings.agent_mode and agent_token and x_api_key is not None and hmac.compare_digest(x_api_key, agent_token):
        return
    if not expected and not settings.agent_mode:
        raise HTTPException(status_code=503, detail="Event ingest is disabled: INGEST_API_KEY is not set")
    raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
