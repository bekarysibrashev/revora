"""Add immutable official 1C report control totals.

Revision ID: 20260827_0024
Revises: 20260827_0023
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260827_0024"
down_revision = "20260827_0023"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "official_report_imports" not in tables:
        op.create_table(
            "official_report_imports",
            sa.Column("report_type", sa.String(50), nullable=False),
            sa.Column("period_from", sa.Date(), nullable=False),
            sa.Column("period_to", sa.Date(), nullable=False),
            sa.Column("source_filename", sa.String(500), nullable=False),
            sa.Column("source_hash", sa.String(64), nullable=False),
            sa.Column("imported_by_user_id", sa.UUID(), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("tenant_id", sa.UUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["imported_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "report_type", "period_from", "period_to", "source_hash", name="uq_official_report_import_identity"),
        )
        op.create_index("ix_official_report_imports_tenant_id", "official_report_imports", ["tenant_id"])
        op.create_index("ix_official_report_imports_report_type", "official_report_imports", ["report_type"])
        op.create_index("ix_official_report_imports_is_active", "official_report_imports", ["is_active"])
        op.create_index("ix_official_report_import_active_period", "official_report_imports", ["tenant_id", "period_from", "period_to", "is_active"])
    tables = _tables()
    if "official_report_metrics" not in tables:
        op.create_table(
            "official_report_metrics",
            sa.Column("report_id", sa.UUID(), nullable=False),
            sa.Column("branch_id", sa.UUID(), nullable=True),
            sa.Column("dimension_type", sa.String(30), nullable=False),
            sa.Column("dimension_key", sa.String(300), nullable=False),
            sa.Column("dimension_label", sa.String(500), nullable=False),
            sa.Column("metric_code", sa.String(80), nullable=False),
            sa.Column("value", sa.Numeric(20, 2), nullable=False),
            sa.Column("unit", sa.String(20), server_default="KZT", nullable=False),
            sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("tenant_id", sa.UUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["report_id"], ["official_report_imports.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_official_report_metrics_tenant_id", "official_report_metrics", ["tenant_id"])
        op.create_index("ix_official_report_metrics_report_id", "official_report_metrics", ["report_id"])
        op.create_index("ix_official_report_metrics_branch_id", "official_report_metrics", ["branch_id"])
        op.create_index("ix_official_report_metrics_metric_code", "official_report_metrics", ["metric_code"])
        op.create_index("ix_official_report_metric_lookup", "official_report_metrics", ["tenant_id", "metric_code", "branch_id", "dimension_type"])


def downgrade() -> None:
    op.drop_table("official_report_metrics")
    op.drop_table("official_report_imports")
