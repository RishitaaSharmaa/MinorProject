"""Control-plane models shared by every tenant: workspaces, users, sessions, sales leads.

These live in the default schema only. Per-tenant operational data lives in one
schema per tenant (see `app.tenancy`), created from `Base.metadata`.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ControlBase(DeclarativeBase):
    """Base class for control-plane tables."""


class Tenant(ControlBase):
    """A customer account. Holds contact and billing details only; operational data
    (decisions, items, suppliers, events) lives in the customer's own agent, never here."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(String(16), nullable=False, default="trial")
    trial_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Billing profile. Card numbers are never stored; a payment provider holds those.
    billing_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    billing_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    billing_country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class User(ControlBase):
    """A person who signs in to a workspace."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuthSession(ControlBase):
    """Opaque bearer-token session; only the token's SHA-256 is stored."""

    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IntegrationRequest(ControlBase):
    """A prospective customer's ERP details and free-trial request.

    Holds contact and landscape details only; credentials are never collected.
    """

    __tablename__ = "integration_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    erp_system: Mapped[str] = mapped_column(String(64), nullable=False)
    erp_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    deployment: Mapped[str] = mapped_column(String(16), nullable=False)
    integration_method: Mapped[str] = mapped_column(String(32), nullable=False)
    monthly_po_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    planner_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trial_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
