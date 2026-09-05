"""Connect inbound contacts to the real sales lead funnel.

Revision ID: 20260906_0036
Revises: 20260904_0035
"""

from alembic import op
import sqlalchemy as sa


revision = "20260906_0036"
down_revision = "20260904_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("leads", "branch_id", existing_type=sa.UUID(), nullable=True)
    op.add_column(
        "leads",
        sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE leads SET last_contact_at = created_at WHERE last_contact_at IS NULL")
    op.alter_column(
        "leads", "last_contact_at", existing_type=sa.DateTime(timezone=True), nullable=False
    )
    op.create_index("ix_leads_last_contact_at", "leads", ["last_contact_at"])


def downgrade() -> None:
    op.drop_index("ix_leads_last_contact_at", table_name="leads")
    op.drop_column("leads", "last_contact_at")
    op.alter_column("leads", "branch_id", existing_type=sa.UUID(), nullable=False)
