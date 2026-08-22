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
    table = "whatsapp_channels"
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(table)}
    definitions = {
        "access_token_ciphertext": sa.Column("access_token_ciphertext", sa.Text(), nullable=True),
        "token_expires_at": sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        "connected_by_user_id": sa.Column("connected_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        "connection_mode": sa.Column("connection_mode", sa.String(length=30), nullable=False, server_default="manual"),
    }
    for name, definition in definitions.items():
        if name not in columns:
            op.add_column(table, definition)
    foreign_keys = {
        constraint.get("name") for constraint in inspector.get_foreign_keys(table)
    }
    constraint_name = "fk_whatsapp_channels_connected_by_user_id_users"
    if constraint_name not in foreign_keys:
        op.create_foreign_key(
            constraint_name,
            table,
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
