"""Persist extraction proposals and planner corrections."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_assumption_proposals"
down_revision: str | None = "0003_supplier_delivery_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Create persisted extraction proposal and disposition records."""
    op.create_table(
        "assumption_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("condition", JSONB, nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("warnings", JSONB, nullable=False),
        sa.Column("review_status", sa.String(16), nullable=False),
        sa.Column("final_condition", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("source IN ('llm', 'structured')", name="ck_assumption_proposals_source"),
        sa.CheckConstraint(
            "review_status IN ('pending', 'accepted', 'edited', 'rejected')",
            name="ck_assumption_proposals_review_status",
        ),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_assumption_proposals_decision_review",
        "assumption_proposals",
        ["decision_id", "review_status"],
    )


def downgrade() -> None:
    """Drop extraction proposal records."""
    op.drop_index("ix_assumption_proposals_decision_review", table_name="assumption_proposals")
    op.drop_table("assumption_proposals")