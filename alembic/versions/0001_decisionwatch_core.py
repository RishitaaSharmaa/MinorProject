"""Create namespaced DecisionWatch decision, condition, event, and link tables."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_decisionwatch_core"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the initial DecisionWatch tables and dependency links."""
    op.create_table(
        "dw_decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("decision_type", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("estimated_regret", sa.Float(), nullable=False),
        sa.Column("switching_cost", sa.Float(), nullable=False),
        sa.Column("latest_condition_state", sa.String(length=16), nullable=False),
        sa.Column("latest_flagged", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "dw_conditions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("decision_id", sa.String(length=36), nullable=False),
        sa.Column("entity", sa.String(length=255), nullable=False),
        sa.Column("field", sa.String(length=128), nullable=False),
        sa.Column("operator", sa.String(length=2), nullable=False),
        sa.Column("expected_value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["decision_id"], ["dw_decisions.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "dw_state_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("entity", sa.String(length=255), nullable=False),
        sa.Column("field", sa.String(length=128), nullable=False),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "dw_decision_links",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_decision_id", sa.String(length=36), nullable=False),
        sa.Column("target_decision_id", sa.String(length=36), nullable=False),
        sa.Column("relationship", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["source_decision_id"], ["dw_decisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_decision_id"], ["dw_decisions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_decision_id", "target_decision_id", "relationship"),
    )


def downgrade() -> None:
    """Remove the initial DecisionWatch persistence schema."""
    op.drop_table("dw_state_events")
    op.drop_table("dw_decision_links")
    op.drop_table("dw_conditions")
    op.drop_table("dw_decisions")