"""Store Kcell recordings and accepted history callbacks.

Revision ID: 20260724_0007
Revises: 20260724_0006
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260724_0007"
down_revision = "20260724_0006"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("calls", sa.Column("external_user", sa.String(length=150), nullable=True))
    op.add_column("calls", sa.Column("recording_url", sa.Text(), nullable=True))
    op.create_index("ix_calls_external_user", "calls", ["external_user"])
    op.create_table("kcell_webhook_receipts", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("call_id", sa.String(length=200), nullable=False), sa.Column("command", sa.String(length=50), nullable=False), sa.Column("payload", postgresql.JSONB(), nullable=False), sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("tenant_id", "call_id", "command"))
    op.create_index("ix_kcell_webhook_receipts_tenant_id", "kcell_webhook_receipts", ["tenant_id"])
    op.create_index("ix_kcell_webhook_receipts_call_id", "kcell_webhook_receipts", ["call_id"])
    op.execute('ALTER TABLE "kcell_webhook_receipts" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "kcell_webhook_receipts" FORCE ROW LEVEL SECURITY')
    op.execute('''CREATE POLICY tenant_isolation ON "kcell_webhook_receipts" USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)''')

def downgrade() -> None:
    op.drop_table("kcell_webhook_receipts")
    op.drop_index("ix_calls_external_user", table_name="calls")
    op.drop_column("calls", "recording_url")
    op.drop_column("calls", "external_user")
