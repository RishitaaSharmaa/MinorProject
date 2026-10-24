"""Hosted accounts hold contact and billing details only.

Drops the per-tenant data schema pointer and ingest keys (operational data now lives in the
customer's own agent) and adds the billing profile. Existing `t_<hex>` schemas created by the
earlier design are NOT dropped here; remove them deliberately with `DROP SCHEMA ... CASCADE`.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_account_only_hosted"
down_revision: str | None = "0008_workspaces_and_imports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("billing_name", sa.String(255), nullable=True))
    op.add_column("tenants", sa.Column("billing_email", sa.String(255), nullable=True))
    op.add_column("tenants", sa.Column("billing_address", sa.Text(), nullable=True))
    op.add_column("tenants", sa.Column("billing_country", sa.String(64), nullable=True))
    op.add_column("tenants", sa.Column("tax_id", sa.String(64), nullable=True))
    op.drop_column("tenants", "ingest_key_hash")
    op.drop_column("tenants", "ingest_key_prefix")
    op.drop_column("tenants", "schema_name")


def downgrade() -> None:
    op.add_column("tenants", sa.Column("schema_name", sa.String(64), nullable=True))
    op.add_column("tenants", sa.Column("ingest_key_prefix", sa.String(16), nullable=True))
    op.add_column("tenants", sa.Column("ingest_key_hash", sa.String(64), nullable=True))
    for column in ("tax_id", "billing_country", "billing_address", "billing_email", "billing_name"):
        op.drop_column("tenants", column)
