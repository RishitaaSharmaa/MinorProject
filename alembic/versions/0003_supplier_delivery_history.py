"""Add supplier delivery records required for actual lead-time queries."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_supplier_delivery_history"
down_revision: str | None = "0002_backend_dataset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create promised and actual supplier delivery date storage."""
    op.create_table(
        "supplier_delivery_history",
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("supplier_id", sa.String(32), nullable=False),
        sa.Column("promised_delivery_date", sa.Date(), nullable=False),
        sa.Column("actual_delivery_date", sa.Date(), nullable=False),
        sa.Column("delay_days", sa.Integer(), nullable=False),
        sa.Column("arrived_late", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.supplier_id"]),
        sa.PrimaryKeyConstraint("decision_id"),
    )


def downgrade() -> None:
    """Remove supplier delivery history."""
    op.drop_table("supplier_delivery_history")