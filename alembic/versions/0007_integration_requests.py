"""Create integration_requests for enterprise ERP trial sign-ups."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_integration_requests"
down_revision: str | None = "0006_commitment_link_economics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "integration_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=False),
        sa.Column("contact_email", sa.String(255), nullable=False),
        sa.Column("contact_phone", sa.String(64), nullable=True),
        sa.Column("job_title", sa.String(128), nullable=True),
        sa.Column("erp_system", sa.String(64), nullable=False),
        sa.Column("erp_version", sa.String(128), nullable=True),
        sa.Column("deployment", sa.String(16), nullable=False),
        sa.Column("integration_method", sa.String(32), nullable=False),
        sa.Column("monthly_po_volume", sa.Integer(), nullable=True),
        sa.Column("planner_count", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("consent", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_integration_requests_contact_email", "integration_requests", ["contact_email"])


def downgrade() -> None:
    op.drop_index("ix_integration_requests_contact_email", table_name="integration_requests")
    op.drop_table("integration_requests")
