"""Add tenants, users, sessions (control plane) and import mapping/audit tables.

The tables in the default schema belong to the shared demo workspace. Each customer
workspace gets its own schema, created from the models at sign-up time.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_workspaces_and_imports"
down_revision: str | None = "0007_integration_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("schema_name", sa.String(64), nullable=False, unique=True),
        sa.Column("plan", sa.String(16), nullable=False),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingest_key_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("ingest_key_prefix", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "import_mappings",
        sa.Column("dataset", sa.String(32), primary_key=True),
        sa.Column("mapping", JSON, nullable=False),
        sa.Column("date_format", sa.String(32), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "import_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset", sa.String(32), nullable=False),
        sa.Column("filename", sa.String(255), nullable=True),
        sa.Column("rows_total", sa.Integer(), nullable=False),
        sa.Column("rows_imported", sa.Integer(), nullable=False),
        sa.Column("rows_rejected", sa.Integer(), nullable=False),
        sa.Column("decisions_flagged", sa.Integer(), nullable=False),
        sa.Column("errors_sample", JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in ("import_runs", "import_mappings", "auth_sessions", "users", "tenants"):
        op.drop_table(table)
