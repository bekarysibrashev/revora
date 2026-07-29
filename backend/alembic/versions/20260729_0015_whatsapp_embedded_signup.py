"""Add WhatsApp Embedded Signup credentials.

Revision ID: 20260729_0015
Revises: 20260729_0014
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_0015"
down_revision: str | None = "20260729_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_channels",
        sa.Column("access_token_ciphertext", sa.Text(), nullable=True),
    )
    op.add_column(
        "whatsapp_channels",
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "whatsapp_channels",
        sa.Column(
            "connected_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "whatsapp_channels",
        sa.Column(
            "connection_mode",
            sa.String(length=30),
            nullable=False,
            server_default="manual",
        ),
    )
    op.create_foreign_key(
        "fk_whatsapp_channels_connected_by_user_id_users",
        "whatsapp_channels",
        "users",
        ["connected_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_whatsapp_channels_connected_by_user_id_users",
        "whatsapp_channels",
        type_="foreignkey",
    )
    op.drop_column("whatsapp_channels", "connection_mode")
    op.drop_column("whatsapp_channels", "connected_by_user_id")
    op.drop_column("whatsapp_channels", "token_expires_at")
    op.drop_column("whatsapp_channels", "access_token_ciphertext")
