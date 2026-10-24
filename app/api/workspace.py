"""Account, billing and (agent-only) self-serve data-import routes."""

import re
from functools import lru_cache
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_control_db, get_db
from app.ratelimit import RateLimiter, client_key
from app.models import AuthSession, ImportRun, Tenant, User
from app.services import importer
from app.services.sync import last_sync_runs, sync_from_source, sync_lock
from app.sources import SourceError, get_source
from app.tenancy import (
    Workspace,
    aware,
    create_tenant,
    hash_password,
    issue_session,
    resolve_workspace,
    sha256,
    trial_expired,
    utcnow,
    verify_password,
    bearer_token,
)

router = APIRouter()

EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """Hash checked for unknown emails so login time does not reveal which accounts exist."""
    return hash_password("not-a-real-password")


_signup_limiter = RateLimiter(limit=10, window_seconds=3600)
_login_limiter = RateLimiter(limit=10, window_seconds=300)


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    company_name: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(max_length=255, pattern=EMAIL)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(max_length=255)
    password: str = Field(max_length=128)


class UserOut(BaseModel):
    name: str
    email: str
    role: str


class TenantOut(BaseModel):
    id: str
    name: str
    plan: str
    trial_ends_at: datetime
    trial_days_left: int
    trial_expired: bool


class WorkspaceOut(BaseModel):
    demo: bool
    auth_required: bool
    agent: bool = False
    user: UserOut | None = None
    tenant: TenantOut | None = None


class AuthOut(BaseModel):
    token: str
    workspace: WorkspaceOut


class BillingIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    billing_name: str = Field(min_length=1, max_length=255)
    billing_email: str = Field(max_length=255, pattern=EMAIL)
    billing_address: str = Field(min_length=1, max_length=1000)
    billing_country: str = Field(min_length=2, max_length=64)
    tax_id: str | None = Field(default=None, max_length=64)


class BillingOut(BaseModel):
    billing_name: str | None
    billing_email: str | None
    billing_address: str | None
    billing_country: str | None
    tax_id: str | None


def _workspace_out(workspace: Workspace) -> WorkspaceOut:
    settings = get_settings()
    if workspace.agent:
        return WorkspaceOut(demo=False, auth_required=True, agent=True)
    if workspace.tenant is None:
        return WorkspaceOut(demo=True, auth_required=settings.auth_required)
    tenant = workspace.tenant
    left = (aware(tenant.trial_ends_at) - utcnow()).total_seconds() / 86400
    return WorkspaceOut(
        demo=False,
        auth_required=settings.auth_required,
        user=UserOut(name=workspace.user.name, email=workspace.user.email, role=workspace.user.role)
        if workspace.user else None,
        tenant=TenantOut(
            id=tenant.id, name=tenant.name, plan=tenant.plan, trial_ends_at=tenant.trial_ends_at,
            trial_days_left=max(0, int(left) + (1 if left % 1 else 0)),
            trial_expired=trial_expired(tenant),
        ),
    )


def _no_agent() -> None:
    if get_settings().agent_mode:
        raise HTTPException(status_code=404, detail="Accounts are managed by the hosted site, not this agent")


def _agent_only(request: Request, control: Session = Depends(get_control_db)) -> Workspace:
    """Data import runs on the customer's own agent; the hosted site never accepts files."""
    workspace = resolve_workspace(request, control)
    if not workspace.agent:
        raise HTTPException(status_code=403, detail="Imports run on your own agent. Connect it to load your data.")
    return workspace


def _account(request: Request, control: Session = Depends(get_control_db)) -> Workspace:
    """Require a signed-in hosted account."""
    workspace = resolve_workspace(request, control)
    if workspace.tenant is None or workspace.user is None:
        raise HTTPException(status_code=403, detail="Sign in to manage your account")
    return workspace


@router.post("/auth/signup", response_model=AuthOut, status_code=201)
def signup(body: SignupRequest, request: Request, control: Session = Depends(get_control_db)) -> AuthOut:
    """Create a workspace with a free trial and its first (owner) user."""
    _no_agent()
    _signup_limiter.check(client_key(request))
    email = body.email.lower()
    if control.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    tenant = create_tenant(control, body.company_name)
    user = User(
        id=str(uuid4()), tenant_id=tenant.id, email=email, name=body.name,
        password_hash=hash_password(body.password), role="owner", created_at=utcnow(),
    )
    control.add(user)
    try:
        control.commit()
    except IntegrityError as exc:  # a concurrent sign-up took the email
        control.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists") from exc
    token = issue_session(control, user)
    return AuthOut(token=token, workspace=_workspace_out(Workspace(tenant=tenant, user=user)))


@router.post("/auth/login", response_model=AuthOut)
def login(body: LoginRequest, request: Request, control: Session = Depends(get_control_db)) -> AuthOut:
    _no_agent()
    email = body.email.lower()
    _login_limiter.check(client_key(request, email))
    user = control.scalar(select(User).where(User.email == email))
    valid = verify_password(body.password, user.password_hash if user else _dummy_hash())
    if user is None or not valid:
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    tenant = control.get(Tenant, user.tenant_id)
    return AuthOut(token=issue_session(control, user), workspace=_workspace_out(Workspace(tenant=tenant, user=user)))


@router.post("/auth/logout", status_code=204)
def logout(request: Request, control: Session = Depends(get_control_db)) -> None:
    token = bearer_token(request)
    session = control.get(AuthSession, sha256(token)) if token else None
    if session is not None:
        control.delete(session)
        control.commit()


@router.get("/auth/me", response_model=WorkspaceOut)
def me(request: Request, control: Session = Depends(get_control_db)) -> WorkspaceOut:
    """Describe the current workspace: the shared demo, or the signed-in tenant and its trial."""
    return _workspace_out(resolve_workspace(request, control))


@router.get("/workspace/billing", response_model=BillingOut)
def get_billing(workspace: Workspace = Depends(_account), control: Session = Depends(get_control_db)) -> Tenant:
    """The account's billing profile (contact details only; never card numbers)."""
    return control.get(Tenant, workspace.tenant.id)


@router.put("/workspace/billing", response_model=BillingOut)
def put_billing(
    body: BillingIn, workspace: Workspace = Depends(_account), control: Session = Depends(get_control_db),
) -> Tenant:
    tenant = control.get(Tenant, workspace.tenant.id)
    for field, value in body.model_dump().items():
        setattr(tenant, field, value or None)
    control.commit()
    return tenant


# --- Self-serve data import -------------------------------------------------------------


class FieldOut(BaseModel):
    name: str
    kind: str
    required: bool
    description: str


class DatasetOut(BaseModel):
    name: str
    title: str
    description: str
    key: str
    depends_on: list[str]
    fields: list[FieldOut]


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str | None = Field(default=None, max_length=255)
    csv_text: str = Field(min_length=1, max_length=15_000_000)
    mapping: dict[str, str] | None = None
    date_format: str | None = None
    skip_invalid: bool = False


class RowErrorOut(BaseModel):
    row: int
    field: str | None
    message: str


class ImportPreview(BaseModel):
    dataset: str
    headers: list[str]
    suggested_mapping: dict[str, str]
    mapping: dict[str, str]
    date_format: str | None
    missing_required: list[str]
    total_rows: int
    valid_rows: int
    error_rows: int
    errors: list[RowErrorOut]
    sample: list[dict[str, Any]]


class ImportRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset: str
    filename: str | None
    rows_total: int
    rows_imported: int
    rows_rejected: int
    decisions_flagged: int
    errors_sample: list[Any]
    created_at: datetime


class SavedMappingOut(BaseModel):
    dataset: str
    mapping: dict[str, str]
    date_format: str | None


class SyncDatasetOut(BaseModel):
    dataset: str
    fetched: int
    imported: int
    rejected: int
    errors: list[Any]


class SyncOut(BaseModel):
    source: str
    started_at: datetime
    finished_at: datetime | None
    datasets: list[SyncDatasetOut]
    change_events: int
    decisions_flagged: int
    warnings: list[str]


class SyncStatusOut(BaseModel):
    configured: bool
    source: str | None
    interval_minutes: int
    runs: list[ImportRunOut]


class SyncCheckOut(BaseModel):
    message: str


def _dataset_out(spec: importer.DatasetSpec) -> DatasetOut:
    return DatasetOut(
        name=spec.name, title=spec.title, description=spec.description, key=spec.key,
        depends_on=list(spec.depends_on),
        fields=[FieldOut(name=f.name, kind=f.kind, required=f.required, description=f.description) for f in spec.fields],
    )


def _analyze(session: Session, dataset: str, body: ImportRequest) -> importer.Analysis:
    try:
        return importer.analyze(session, dataset, body.csv_text, body.mapping, body.date_format)
    except importer.ImportFailure as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/import/datasets", response_model=list[DatasetOut])
def import_datasets() -> list[DatasetOut]:
    """The canonical datasets a workspace can load, in the order they should be imported."""
    return [_dataset_out(spec) for spec in importer.DATASETS.values()]


@router.get("/import/runs", response_model=list[ImportRunOut])
def import_runs(_: Workspace = Depends(_agent_only), session: Session = Depends(get_db)) -> list[ImportRun]:
    return list(session.scalars(select(ImportRun).order_by(ImportRun.created_at.desc()).limit(50)))


@router.get("/import/{dataset}/mapping", response_model=SavedMappingOut | None)
def saved_mapping(
    dataset: str, _: Workspace = Depends(_agent_only), session: Session = Depends(get_db),
) -> SavedMappingOut | None:
    if dataset not in importer.DATASETS:
        raise HTTPException(status_code=404, detail=f"Unknown dataset {dataset!r}")
    saved = importer.get_saved_mapping(session, dataset)
    return SavedMappingOut(dataset=dataset, mapping=saved.mapping, date_format=saved.date_format) if saved else None


@router.post("/import/{dataset}/preview", response_model=ImportPreview)
def import_preview(
    dataset: str, body: ImportRequest, _: Workspace = Depends(_agent_only), session: Session = Depends(get_db),
) -> ImportPreview:
    """Validate an upload and show how it will be read. Writes nothing."""
    if body.mapping is None:
        saved = importer.get_saved_mapping(session, dataset)
        if saved is not None:
            headers_ok = importer.parse_csv(body.csv_text)[0] if body.csv_text.strip() else []
            if all(column in headers_ok for column in saved.mapping.values()):
                body = body.model_copy(update={
                    "mapping": saved.mapping, "date_format": body.date_format or saved.date_format,
                })
    analysis = _analyze(session, dataset, body)
    return ImportPreview(
        dataset=dataset, headers=analysis.headers, suggested_mapping=analysis.suggested_mapping,
        mapping=analysis.mapping, date_format=body.date_format, missing_required=analysis.missing_required,
        total_rows=analysis.total_rows,
        valid_rows=len(analysis.rows), error_rows=analysis.error_rows,
        errors=[RowErrorOut(**e.as_dict()) for e in analysis.errors[:importer.MAX_ERRORS_REPORTED]],
        sample=importer.sample_rows(analysis),
    )


@router.post("/import/{dataset}/commit", response_model=ImportRunOut, status_code=201)
def import_commit(
    dataset: str, body: ImportRequest, _: Workspace = Depends(_agent_only), session: Session = Depends(get_db),
) -> ImportRun:
    """Import the file with the confirmed mapping and remember that mapping for next time."""
    analysis = _analyze(session, dataset, body)
    try:
        return importer.commit_import(
            session, analysis, filename=body.filename, date_format=body.date_format, skip_invalid=body.skip_invalid,
        )
    except importer.ImportFailure as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# --- ERP sync (agent only) --------------------------------------------------------------


def _source():
    try:
        source = get_source()
    except SourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if source is None:
        raise HTTPException(status_code=409, detail="No ERP is configured on this agent. Set ERP_SOURCE and its credentials.")
    return source


@router.get("/sync/status", response_model=SyncStatusOut)
def sync_status(_: Workspace = Depends(_agent_only), session: Session = Depends(get_db)) -> SyncStatusOut:
    """Whether an ERP is configured and what the latest syncs loaded."""
    settings = get_settings()
    return SyncStatusOut(
        configured=bool(settings.erp_source.strip()), source=settings.erp_source.strip() or None,
        interval_minutes=settings.sync_interval_minutes, runs=list(last_sync_runs(session)),
    )


@router.post("/sync/test", response_model=SyncCheckOut)
def sync_test(_: Workspace = Depends(_agent_only)) -> SyncCheckOut:
    """Check the ERP credentials without loading anything."""
    source = _source()
    try:
        with source:
            return SyncCheckOut(message=source.check())
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/sync", response_model=SyncOut)
def sync_now(_: Workspace = Depends(_agent_only), session: Session = Depends(get_db)) -> SyncOut:
    """Read everything from the configured ERP into this agent's database."""
    source = _source()
    if not sync_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A sync is already running")
    try:
        summary = sync_from_source(session, source)
    except SourceError as exc:
        session.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        sync_lock.release()
    return SyncOut(
        source=summary.source, started_at=summary.started_at, finished_at=summary.finished_at,
        datasets=[SyncDatasetOut(**vars(d)) for d in summary.datasets], change_events=summary.change_events,
        decisions_flagged=summary.decisions_flagged, warnings=summary.warnings,
    )
