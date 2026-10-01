"""Purchase decisions, assumptions, violations, commitments, and outcomes."""

from datetime import date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSON_VALUE


class Decision(Base):
    """Recorded purchase order or MRP override."""

    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_type: Mapped[str] = mapped_column("type", String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    structured_fields: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, nullable=False)
    free_text_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_override: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    item_id: Mapped[str | None] = mapped_column(ForeignKey("items.item_id"), nullable=True)
    supplier_id: Mapped[str | None] = mapped_column(ForeignKey("suppliers.supplier_id"), nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    po_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_delivery: Mapped[date | None] = mapped_column(Date, nullable=True)


class Assumption(Base):
    """Operational assumption attached to a decision, excluding answer keys."""

    __tablename__ = "assumptions"
    __table_args__ = (
        CheckConstraint("source IN ('llm', 'manual', 'structured')", name="ck_assumptions_source"),
        CheckConstraint("status IN ('live', 'violated', 'retired')", name="ck_assumptions_status"),
        Index("ix_assumptions_decision_status", "decision_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id", ondelete="CASCADE"), nullable=False)
    condition: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    confirmed_by_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="live", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AssumptionProposal(Base):
    """Original extraction proposal and planner disposition for correction metrics."""

    __tablename__ = "assumption_proposals"
    __table_args__ = (
        CheckConstraint("source IN ('llm', 'structured')", name="ck_assumption_proposals_source"),
        CheckConstraint(
            "review_status IN ('pending', 'accepted', 'edited', 'rejected')",
            name="ck_assumption_proposals_review_status",
        ),
        Index("ix_assumption_proposals_decision_review", "decision_id", "review_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id", ondelete="CASCADE"), nullable=False)
    condition: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON_VALUE, nullable=False)
    review_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    final_condition: Mapped[dict[str, Any] | None] = mapped_column(JSON_VALUE, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssumptionViolation(Base):
    """Operational link between a non-answer-key assumption and event."""

    __tablename__ = "assumption_violations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    assumption_id: Mapped[str] = mapped_column(ForeignKey("assumptions.id", ondelete="CASCADE"), nullable=False)
    event_id: Mapped[str] = mapped_column(ForeignKey("state_events.id", ondelete="CASCADE"), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Commitment(Base):
    """Cancellation and reversibility economics for a purchase decision."""

    __tablename__ = "commitments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id", ondelete="CASCADE"), unique=True)
    cancellation_fee_pct: Mapped[float] = mapped_column(Float, nullable=False)
    reversible_until: Mapped[date] = mapped_column(Date, nullable=False)
    linked_commitment_id: Mapped[str | None] = mapped_column(
        ForeignKey("commitments.id", ondelete="SET NULL"), nullable=True
    )


#: Closed vocabulary of reasons two commitments can be linked in the graph.
COMMITMENT_LINK_TYPES = (
    "freight_consolidation",
    "volume_discount",
    "moq_pool",
    "bundled_shipment",
    "other",
)


class CommitmentLink(Base):
    """Undirected-capable edge between supplier-consolidated commitments."""

    __tablename__ = "commitment_links"
    __table_args__ = (
        UniqueConstraint("from_commitment_id", "to_commitment_id", name="uq_commitment_links_edge"),
        CheckConstraint("from_commitment_id <> to_commitment_id", name="ck_commitment_links_no_self"),
        CheckConstraint(
            "link_type IN ('freight_consolidation', 'volume_discount', 'moq_pool', 'bundled_shipment', 'other')",
            name="ck_commitment_links_link_type",
        ),
        Index("ix_commitment_links_from", "from_commitment_id"),
        Index("ix_commitment_links_to", "to_commitment_id"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    from_commitment_id: Mapped[str] = mapped_column(
        ForeignKey("commitments.id", ondelete="CASCADE"), nullable=False
    )
    to_commitment_id: Mapped[str] = mapped_column(
        ForeignKey("commitments.id", ondelete="CASCADE"), nullable=False
    )
    link_type: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    savings_at_stake: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class Outcome(Base):
    """Observed result after a procurement decision is revisited."""

    __tablename__ = "outcomes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id", ondelete="CASCADE"), unique=True)
    recommended_action: Mapped[str] = mapped_column(String(64), nullable=False)
    actual_action: Mapped[str] = mapped_column(String(64), nullable=False)
    actual_result: Mapped[str] = mapped_column(String(64), nullable=False)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)