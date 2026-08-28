"""Store contact phone numbers encrypted for authorized lists and exports.

Revision ID: 20260828_0025
Revises: 20260827_0024
"""

from alembic import op
import sqlalchemy as sa


revision = "20260828_0025"
down_revision = "20260827_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contact_identities", sa.Column("phone_ciphertext", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("contact_identities", "phone_ciphertext")
