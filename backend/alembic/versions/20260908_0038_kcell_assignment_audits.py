"""Audit trail for Kcell extension assignment changes.

The extension -> employee mapping decides who gets credited for a lead, so
every change to it (and every backfill that applies it to old leads) needs
to be attributable. Deliberately stores no phone number and no phone_hash:
a record of configuration changes never needs patient identifiers.

Revision ID: 20260908_0038
Revises: 20260908_0037
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260908_0038"
down_revision = "20260908_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kcell_assignment_audits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_user", sa.String(length=150), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column(
            "previous_assigned_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "new_assigned_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "changed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_kcell_assignment_audits_tenant_id",
        "kcell_assignment_audits",
        ["tenant_id"],
    )
    op.create_index(
        "ix_kcell_assignment_audits_external_user",
        "kcell_assignment_audits",
        ["external_user"],
    )

    # Same isolation the rest of the tenant-scoped tables use: the audit
    # trail of one clinic's assignments must never be readable by another.
    op.execute("ALTER TABLE kcell_assignment_audits ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kcell_assignment_audits FORCE ROW LEVEL SECURITY")
    # NULLIF guard matches migration 0037: an unset app.tenant_id is the
    # empty string, and casting that to uuid raises instead of denying.
    op.execute(
        '''CREATE POLICY tenant_isolation ON "kcell_assignment_audits" '''
        '''USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) '''
        '''WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)'''
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON kcell_assignment_audits")
    op.drop_index(
        "ix_kcell_assignment_audits_external_user",
        table_name="kcell_assignment_audits",
    )
    op.drop_index(
        "ix_kcell_assignment_audits_tenant_id", table_name="kcell_assignment_audits"
    )
    op.drop_table("kcell_assignment_audits")
