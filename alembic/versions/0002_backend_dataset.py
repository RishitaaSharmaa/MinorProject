"""Create the procurement backend tables and isolated ground-truth tables."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_backend_dataset"
down_revision: str | None = "0001_decisionwatch_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Create normalized application and answer-key persistence tables."""
    op.create_table(
        "suppliers",
        sa.Column("supplier_id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("quoted_lead_time_days", sa.Integer(), nullable=False),
        sa.Column("lead_time_std_dev", sa.Float(), nullable=False),
        sa.Column("reliability_score", sa.Float(), nullable=False),
        sa.Column("price_break_tiers", JSONB, nullable=False),
        sa.Column("strike_status", sa.String(32), nullable=False),
    )
    op.create_table(
        "items",
        sa.Column("item_id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(128), nullable=False),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("holding_cost_pct", sa.Numeric(6, 3), nullable=False),
        sa.Column("min_order_qty", sa.Integer(), nullable=False),
        sa.Column("primary_supplier_id", sa.String(32), nullable=False),
        sa.Column("avg_daily_demand", sa.Integer(), nullable=False),
        sa.Column("reorder_point_qty", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["primary_supplier_id"], ["suppliers.supplier_id"]),
    )
    for table_name in ("sales_history", "stock_snapshots", "forecasts"):
        columns = [
            sa.Column("item_id", sa.String(32), nullable=False),
            sa.Column("date" if table_name != "forecasts" else "week", sa.Date(), nullable=False),
        ]
        if table_name == "sales_history":
            columns.append(sa.Column("qty_sold", sa.Integer(), nullable=False))
        elif table_name == "stock_snapshots":
            columns.append(sa.Column("qty_on_hand", sa.Integer(), nullable=False))
        else:
            columns.extend([
                sa.Column("forecast_qty", sa.Integer(), nullable=False),
                sa.Column("true_demand", sa.Integer(), nullable=False),
                sa.Column("forecast_error_pct", sa.Float(), nullable=False),
            ])
        columns.extend([
            sa.PrimaryKeyConstraint("item_id", "date" if table_name != "forecasts" else "week"),
            sa.ForeignKeyConstraint(["item_id"], ["items.item_id"], ondelete="CASCADE"),
        ])
        op.create_table(table_name, *columns)

    op.create_table(
        "decisions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("structured_fields", JSONB, nullable=False),
        sa.Column("free_text_reason", sa.Text(), nullable=True),
        sa.Column("is_override", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("item_id", sa.String(32), nullable=True),
        sa.Column("supplier_id", sa.String(32), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("unit_price", sa.Float(), nullable=True),
        sa.Column("po_date", sa.Date(), nullable=True),
        sa.Column("expected_delivery", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["items.item_id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.supplier_id"]),
    )
    op.create_table(
        "assumptions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("condition", JSONB, nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("confirmed_by_user", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source IN ('llm', 'manual', 'structured')", name="ck_assumptions_source"),
        sa.CheckConstraint("status IN ('live', 'violated', 'retired')", name="ck_assumptions_status"),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_assumptions_decision_status", "assumptions", ["decision_id", "status"])

    op.create_table(
        "state_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(255), nullable=False),
        sa.Column("field", sa.String(128), nullable=False),
        sa.Column("old_value", JSONB, nullable=True),
        sa.Column("new_value", JSONB, nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_state_events_entity_time",
        "state_events",
        ["entity_type", "entity_id", "event_time"],
    )
    op.create_table(
        "assumption_violations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("assumption_id", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assumption_id"], ["assumptions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["state_events.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "commitments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("decision_id", sa.String(64), nullable=False, unique=True),
        sa.Column("cancellation_fee_pct", sa.Float(), nullable=False),
        sa.Column("reversible_until", sa.Date(), nullable=False),
        sa.Column("linked_commitment_id", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_commitment_id"], ["commitments.id"], ondelete="SET NULL"),
    )
    op.create_table(
        "outcomes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("decision_id", sa.String(64), nullable=False, unique=True),
        sa.Column("recommended_action", sa.String(64), nullable=False),
        sa.Column("actual_action", sa.String(64), nullable=False),
        sa.Column("actual_result", sa.String(64), nullable=False),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "gt_assumptions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("condition", JSONB, nullable=False),
        sa.Column("confirmed_by_user", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "gt_assumption_violations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("violated_condition", JSONB, nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
    )


def downgrade() -> None:
    """Drop backend and isolated answer-key tables in dependency order."""
    for table_name in (
        "gt_assumption_violations", "gt_assumptions", "outcomes", "commitments",
        "assumption_violations", "state_events", "assumptions", "decisions",
        "forecasts", "stock_snapshots", "sales_history", "items", "suppliers",
    ):
        op.drop_table(table_name)