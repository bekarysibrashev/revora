"""Add owner-configured call quality scoring.

Revision ID: 20260724_0006
Revises: 20260720_0005
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260724_0006"
down_revision = "20260720_0005"
branch_labels = None
depends_on = None

def _rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(f'''CREATE POLICY tenant_isolation ON "{table}" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)''')

def upgrade() -> None:
    op.create_table("call_quality_rule_sets", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("name", sa.String(length=150), nullable=False), sa.Column("success_definition", sa.Text(), nullable=False), sa.Column("partial_success_definition", sa.Text(), nullable=False), sa.Column("loss_definition", sa.Text(), nullable=False), sa.Column("criteria", postgresql.JSONB(), nullable=False), sa.Column("loss_reasons", postgresql.JSONB(), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("tenant_id", "version"))
    op.create_index("ix_call_quality_rule_sets_tenant_id", "call_quality_rule_sets", ["tenant_id"])
    op.create_index("ix_call_quality_rule_sets_is_active", "call_quality_rule_sets", ["is_active"])
    op.create_table("call_quality_analyses", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("call_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("rule_set_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"), sa.Column("result", sa.String(length=30)), sa.Column("score", sa.Integer()), sa.Column("transcript", sa.Text()), sa.Column("summary", sa.Text()), sa.Column("criteria_scores", postgresql.JSONB()), sa.Column("loss_reasons", postgresql.JSONB()), sa.Column("recommendations", postgresql.JSONB()), sa.Column("model_version", sa.String(length=100)), sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["call_id"], ["calls.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["rule_set_id"], ["call_quality_rule_sets.id"], ondelete="RESTRICT"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("tenant_id", "call_id"))
    for table in ("call_quality_rule_sets", "call_quality_analyses"):
        _rls(table)

def downgrade() -> None:
    op.drop_table("call_quality_analyses")
    op.drop_table("call_quality_rule_sets")
