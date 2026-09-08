"""Explicit, administrator-maintained Kcell extension -> User mapping.

Revision ID: 20260908_0037
Revises: 20260906_0036
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260908_0037"
down_revision = "20260906_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kcell_extension_assignments",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_user", sa.String(length=150), nullable=False),
        sa.Column("assigned_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "external_user"),
    )
    op.create_index(
        "ix_kcell_extension_assignments_tenant_id", "kcell_extension_assignments", ["tenant_id"]
    )
    op.create_index(
        "ix_kcell_extension_assignments_external_user", "kcell_extension_assignments", ["external_user"]
    )
    op.create_index(
        "ix_kcell_extension_assignments_assigned_user_id",
        "kcell_extension_assignments",
        ["assigned_user_id"],
    )
    op.execute('ALTER TABLE "kcell_extension_assignments" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "kcell_extension_assignments" FORCE ROW LEVEL SECURITY')
    op.execute(
        '''CREATE POLICY tenant_isolation ON "kcell_extension_assignments" '''
        '''USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) '''
        '''WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)'''
    )


def downgrade() -> None:
    op.drop_table("kcell_extension_assignments")
