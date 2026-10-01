"""SQLAlchemy 2.x persistence models for decisions, conditions, and events."""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSON_VALUE = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    """Declarative root for application tables."""


class DecisionRecord(Base):
    """A procurement decision and its recorded economic review inputs."""

    __tablename__ = "dw_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    decision_type: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    reason: Mapped[str] = mapped_column(String, nullable=False)
    estimated_regret: Mapped[float] = mapped_column(Float, nullable=False)
    switching_cost: Mapped[float] = mapped_column(Float, nullable=False)
    latest_condition_state: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    latest_flagged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    conditions: Mapped[list["ConditionRecord"]] = relationship(
        back_populates="decision", cascade="all, delete-orphan", lazy="selectin"
    )


class ConditionRecord(Base):
    """One structured assumption extracted from or entered for a decision."""

    __tablename__ = "dw_conditions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    decision_id: Mapped[str] = mapped_column(ForeignKey("dw_decisions.id", ondelete="CASCADE"), nullable=False)
    entity: Mapped[str] = mapped_column(String(255), nullable=False)
    field: Mapped[str] = mapped_column(String(128), nullable=False)
    operator: Mapped[str] = mapped_column(String(2), nullable=False)
    expected_value: Mapped[Any] = mapped_column(JSON_VALUE, nullable=False)
    decision: Mapped[DecisionRecord] = relationship(back_populates="conditions")


class StateEventRecord(Base):
    """Persisted state-change event received from an ERP connector."""

    __tablename__ = "dw_state_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entity: Mapped[str] = mapped_column(String(255), nullable=False)
    field: Mapped[str] = mapped_column(String(128), nullable=False)
    old_value: Mapped[Any | None] = mapped_column(JSON_VALUE, nullable=True)
    new_value: Mapped[Any] = mapped_column(JSON_VALUE, nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class DecisionLinkRecord(Base):
    """Directed dependency link used to relate decisions and commitments."""

    __tablename__ = "dw_decision_links"
    __table_args__ = (UniqueConstraint("source_decision_id", "target_decision_id", "relationship"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_decision_id: Mapped[str] = mapped_column(
        ForeignKey("dw_decisions.id", ondelete="CASCADE"), nullable=False
    )
    target_decision_id: Mapped[str] = mapped_column(
        ForeignKey("dw_decisions.id", ondelete="CASCADE"), nullable=False
    )
    relationship: Mapped[str] = mapped_column(String(64), default="depends_on", nullable=False)