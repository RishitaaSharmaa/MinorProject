"""Store commitment graph edges for cycle-safe sibling walks."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_commitment_links"
down_revision: str | None = "0004_assumption_proposals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create commitment_links and backfill from the legacy self-FK column."""
    op.create_table(
        "commitment_links",
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("from_commitment_id", sa.String(64), nullable=False),
        sa.Column("to_commitment_id", sa.String(64), nullable=False),
        sa.CheckConstraint("from_commitment_id <> to_commitment_id", name="ck_commitment_links_no_self"),
        sa.ForeignKeyConstraint(["from_commitment_id"], ["commitments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_commitment_id"], ["commitments.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("from_commitment_id", "to_commitment_id", name="uq_commitment_links_edge"),
    )
    op.create_index("ix_commitment_links_from", "commitment_links", ["from_commitment_id"])
    op.create_index("ix_commitment_links_to", "commitment_links", ["to_commitment_id"])
    op.execute(
        sa.text(
            "INSERT INTO commitment_links (id, from_commitment_id, to_commitment_id) "
            "SELECT 'CL-' || id || '-' || linked_commitment_id, id, linked_commitment_id "
            "FROM commitments WHERE linked_commitment_id IS NOT NULL"
        )
    )


def downgrade() -> None:
    """Drop commitment graph edges."""
    op.drop_index("ix_commitment_links_to", table_name="commitment_links")
    op.drop_index("ix_commitment_links_from", table_name="commitment_links")
    op.drop_table("commitment_links")
