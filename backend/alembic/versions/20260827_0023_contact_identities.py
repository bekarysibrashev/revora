"""Add a cross-channel first-contact registry.

Revision ID: 20260827_0023
Revises: 20260827_0022
"""

from alembic import op
import sqlalchemy as sa


revision = "20260827_0023"
down_revision = "20260827_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contact_identities",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("phone_hash", sa.String(length=64), nullable=False),
        sa.Column("phone_masked", sa.String(length=30), nullable=True),
        sa.Column("first_inbound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_inbound_source", sa.String(length=30), nullable=False),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_inbound_source", sa.String(length=30), nullable=False),
        sa.Column("inbound_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("call_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("message_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("was_known_patient", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "phone_hash"),
    )
    for column in ("tenant_id", "phone_hash", "first_inbound_at", "first_inbound_source", "last_inbound_at", "was_known_patient"):
        op.create_index(f"ix_contact_identities_{column}", "contact_identities", [column])
    op.execute('ALTER TABLE "contact_identities" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "contact_identities" FORCE ROW LEVEL SECURITY')
    op.execute('''CREATE POLICY tenant_isolation ON "contact_identities"
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)''')


def downgrade() -> None:
    op.drop_table("contact_identities")
