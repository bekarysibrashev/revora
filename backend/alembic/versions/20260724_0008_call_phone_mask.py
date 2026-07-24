"""Add privacy-safe phone display for call journal.

Revision ID: 20260724_0008
Revises: 20260724_0007
"""
from alembic import op
import sqlalchemy as sa

revision = "20260724_0008"
down_revision = "20260724_0007"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("calls", sa.Column("phone_masked", sa.String(length=30), nullable=True))

def downgrade() -> None:
    op.drop_column("calls", "phone_masked")
