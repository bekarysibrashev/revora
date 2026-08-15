"""Store the latest field-level 1C OData schema inventory.

Revision ID: 20260815_0018
Revises: 20260811_0017
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260815_0018"
down_revision: str | None = "20260811_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "one_c_metadata_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("schema_version", sa.String(length=100), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("entities", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["integration_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "connection_id"),
    )
    op.create_index("ix_one_c_metadata_snapshots_tenant_id", "one_c_metadata_snapshots", ["tenant_id"])
    op.create_index("ix_one_c_metadata_snapshots_connection_id", "one_c_metadata_snapshots", ["connection_id"])
    op.create_index("ix_one_c_metadata_snapshots_fingerprint", "one_c_metadata_snapshots", ["fingerprint"])
    op.execute('ALTER TABLE "one_c_metadata_snapshots" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "one_c_metadata_snapshots" FORCE ROW LEVEL SECURITY')
    op.execute('''CREATE POLICY tenant_isolation ON "one_c_metadata_snapshots"
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)''')


def downgrade() -> None:
    op.drop_table("one_c_metadata_snapshots")
