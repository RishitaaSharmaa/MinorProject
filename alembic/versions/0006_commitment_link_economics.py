"""Add link_type and savings_at_stake to commitment_links."""

from typing import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_commitment_link_economics"
down_revision: str | None = "0005_commitment_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "commitment_links",
        sa.Column("link_type", sa.String(32), nullable=False, server_default="other"),
    )
    op.add_column(
        "commitment_links",
        sa.Column("savings_at_stake", sa.Float(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_commitment_links_link_type",
        "commitment_links",
        "link_type IN ('freight_consolidation', 'volume_discount', 'moq_pool', 'bundled_shipment', 'other')",
    )
    op.alter_column("commitment_links", "link_type", server_default=None)
    op.alter_column("commitment_links", "savings_at_stake", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_commitment_links_link_type", "commitment_links", type_="check")
    op.drop_column("commitment_links", "savings_at_stake")
    op.drop_column("commitment_links", "link_type")
