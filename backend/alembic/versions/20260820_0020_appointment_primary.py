"""Track whether a 1C appointment belongs to a primary patient visit.

Revision ID: 20260820_0020
Revises: 20260816_0019
"""

from alembic import op
import sqlalchemy as sa


revision = "20260820_0020"
down_revision = "20260816_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("is_primary", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "payroll_facts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("branch_id", sa.UUID(), nullable=True),
        sa.Column("external_id", sa.String(length=150), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "external_id"),
    )
    op.create_index("ix_payroll_facts_tenant_id", "payroll_facts", ["tenant_id"])
    op.create_index("ix_payroll_facts_branch_id", "payroll_facts", ["branch_id"])
    op.create_index("ix_payroll_facts_occurred_on", "payroll_facts", ["occurred_on"])
    op.execute('ALTER TABLE "payroll_facts" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "payroll_facts" FORCE ROW LEVEL SECURITY')
    op.execute('''CREATE POLICY tenant_isolation ON "payroll_facts"
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)''')


def downgrade() -> None:
    op.drop_table("payroll_facts")
    op.drop_column("appointments", "is_primary")
