"""Allow full OData entity names in immutable raw storage.

Revision ID: 20260828_0027
Revises: 20260828_0026
"""

from alembic import op
import sqlalchemy as sa


revision = "20260828_0027"
down_revision = "20260828_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "raw_records",
        "source_entity",
        existing_type=sa.String(length=100),
        type_=sa.String(length=200),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "raw_records",
        "source_entity",
        existing_type=sa.String(length=200),
        type_=sa.String(length=100),
        existing_nullable=False,
    )
