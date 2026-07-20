"""Add tenant-aware raw ingestion and normalization lineage."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260720_0004"
down_revision: str | None = "20260718_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "mapping_profiles",
    "raw_records",
    "normalization_errors",
    "record_lineage",
)


def upgrade() -> None:
    op.create_table(
        "mapping_profiles",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_entity", sa.String(100), nullable=False),
        sa.Column("target_entity", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rules", postgresql.JSONB(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["integration_connections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "connection_id", "source_entity", "target_entity", "version"
        ),
    )
    op.create_index("ix_mapping_profiles_tenant_id", "mapping_profiles", ["tenant_id"])
    op.create_index("ix_mapping_profiles_connection_id", "mapping_profiles", ["connection_id"])
    op.create_index("ix_mapping_profiles_source_entity", "mapping_profiles", ["source_entity"])
    op.create_index("ix_mapping_profiles_target_entity", "mapping_profiles", ["target_entity"])
    op.create_index("ix_mapping_profiles_is_active", "mapping_profiles", ["is_active"])

    op.create_table(
        "raw_records",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sync_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("source_entity", sa.String(100), nullable=False),
        sa.Column("source_record_id", sa.String(200)),
        sa.Column("source_schema_version", sa.String(100)),
        sa.Column("record_hash", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["integration_connections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["sync_run_id"], ["sync_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "connection_id", "source_entity", "record_hash"),
    )
    for column in (
        "tenant_id",
        "connection_id",
        "sync_run_id",
        "source_entity",
        "source_record_id",
        "status",
        "received_at",
    ):
        op.create_index(f"ix_raw_records_{column}", "raw_records", [column])

    op.create_table(
        "normalization_errors",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mapping_profile_id", postgresql.UUID(as_uuid=True)),
        sa.Column("error_code", sa.String(80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("field_name", sa.String(150)),
        sa.Column("raw_value", postgresql.JSONB()),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["mapping_profile_id"], ["mapping_profiles.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("tenant_id", "raw_record_id", "error_code", "status"):
        op.create_index(
            f"ix_normalization_errors_{column}", "normalization_errors", [column]
        )

    op.create_table(
        "record_lineage",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mapping_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_entity", sa.String(100), nullable=False),
        sa.Column("target_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transformed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["mapping_profile_id"], ["mapping_profiles.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raw_record_id", "target_entity", "target_record_id"),
    )
    for column in ("tenant_id", "raw_record_id", "target_entity", "target_record_id"):
        op.create_index(f"ix_record_lineage_{column}", "record_lineage", [column])

    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'''CREATE POLICY tenant_isolation ON "{table}"
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)'''
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
