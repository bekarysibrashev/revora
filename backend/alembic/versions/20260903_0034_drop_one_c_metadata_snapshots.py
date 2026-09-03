"""Drop one_c_metadata_snapshots, the last table exclusive to the retired
1C OData push connector.

Revision ID: 20260903_0034
Revises: 20260902_0033

Part of retiring the old OData/PowerShell integration in favour of the 1C
extension pushing pre-aggregated report snapshots (POST
/api/v1/integrations/1c/report-snapshot). This table only ever held the
localhost connector's $metadata inventory (entity/field names, never row
data) and is read/written exclusively by code removed in this same change
(ingest_one_c_metadata, get_one_c_metadata, upsert_one_c_metadata).

Deliberately NOT touched here: raw_records, sync_runs, normalization_errors,
record_lineage and mapping_profiles. Those tables are also used by the
generic manual tabular-file-upload path (IntegrationService.ingest /
create_mapping_profile), confirmed by reading every caller before writing
this migration -- they are not exclusive to the old 1C connector and must
stay.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260903_0034"
down_revision: str | None = "20260902_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("one_c_metadata_snapshots")


def downgrade() -> None:
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
