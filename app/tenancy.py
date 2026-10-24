"""Accounts, password and session handling, and per-request workspace resolution.

The hosted site stores accounts (email, name, company, billing details) and nothing else.
A request is one of: the shared synthetic demo (no account), a signed-in account (which has
no operational data here), or a customer-run agent (single tenant, its own database).
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuthSession, Tenant, User

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


@dataclass(frozen=True)
class Workspace:
    """The tenant (and user) a request acts for; `tenant is None` means the demo workspace."""

    tenant: Tenant | None = None
    user: User | None = None
    agent: bool = False  # self-hosted single-tenant deployment; data lives in the default schema


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except ValueError:
        return False


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def issue_session(control: Session, user: User) -> str:
    """Create a bearer session for `user` and return the plaintext token (shown once)."""
    token = secrets.token_urlsafe(32)
    now = utcnow()
    control.add(AuthSession(
        token_hash=sha256(token), user_id=user.id, created_at=now,
        expires_at=now + timedelta(days=get_settings().session_ttl_days),
    ))
    control.commit()
    return token


def trial_expired(tenant: Tenant) -> bool:
    return tenant.plan == "trial" and aware(tenant.trial_ends_at) < utcnow()


def create_tenant(control: Session, name: str) -> Tenant:
    """Register an account with a fresh trial. No data storage is provisioned."""
    now = utcnow()
    tenant = Tenant(
        id=str(uuid4()), name=name, plan="trial",
        trial_ends_at=now + timedelta(days=get_settings().trial_days), created_at=now,
    )
    control.add(tenant)
    control.flush()
    return tenant


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def _agent_workspace(request: Request) -> Workspace:
    """Agent mode: one customer, one shared secret. Fail closed if no token is configured."""
    if get_settings().local_mode:
        return Workspace(agent=True)  # in-browser engine: its only caller is the page that hosts it
    expected = get_settings().agent_token.get_secret_value()
    if not expected:
        raise HTTPException(status_code=503, detail="Agent is not configured: AGENT_TOKEN is not set")
    supplied = bearer_token(request) or request.headers.get("x-api-key") or ""
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing agent token")
    return Workspace(agent=True)


def resolve_workspace(request: Request, control: Session) -> Workspace:
    """Work out which workspace a request belongs to (cached on the request)."""
    cached = getattr(request.state, "workspace", None)
    if cached is not None:
        return cached
    settings = get_settings()
    workspace: Workspace | None = None

    if settings.agent_mode:
        workspace = _agent_workspace(request)
        request.state.workspace = workspace
        return workspace

    token = bearer_token(request)
    if token:
        auth = control.get(AuthSession, sha256(token))
        if auth is None or aware(auth.expires_at) < utcnow():
            raise HTTPException(status_code=401, detail="Session expired or invalid. Sign in again.")
        user = control.get(User, auth.user_id)
        tenant = control.get(Tenant, user.tenant_id) if user else None
        if user is None or tenant is None:
            raise HTTPException(status_code=401, detail="Session expired or invalid. Sign in again.")
        workspace = Workspace(tenant=tenant, user=user)
    else:
        # The operator's global key addresses the shared demo workspace; anything else is refused
        # when auth is required instead of silently falling back to it.
        api_key = request.headers.get("x-api-key")
        global_key = settings.ingest_api_key.get_secret_value()
        key_ok = bool(api_key and global_key and hmac.compare_digest(api_key, global_key))
        if settings.auth_required and not key_ok:
            raise HTTPException(status_code=401, detail="Sign in to access this workspace")
        workspace = Workspace()

    if (
        workspace.tenant is not None
        and request.method not in {"GET", "HEAD", "OPTIONS"}
        and request.url.path != "/workspace/billing"  # let an expired trial still add billing details
        and trial_expired(workspace.tenant)
    ):
        raise HTTPException(status_code=402, detail="Your free trial has ended. Contact us to continue.")
    request.state.workspace = workspace
    return workspace
