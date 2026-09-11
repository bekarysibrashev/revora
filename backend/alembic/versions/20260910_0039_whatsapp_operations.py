"""Add durable WhatsApp operations, delivery, media and monitoring data.

Revision ID: 20260910_0039
Revises: 20260905_0036, 20260908_0038
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.database import Base
import app.models  # noqa: F401


revision: str = "20260910_0039"
down_revision: tuple[str, str] = ("20260905_0036", "20260908_0038")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_policy(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'''CREATE POLICY tenant_isolation ON "{table}"
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)'''
    )


def upgrade() -> None:
    op.add_column(
        "whatsapp_messages",
        sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "whatsapp_messages",
        sa.Column("next_delivery_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "whatsapp_messages",
        sa.Column("last_delivery_error", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "whatsapp_messages",
        sa.Column("media_mime_type", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "whatsapp_messages",
        sa.Column("media_filename", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "whatsapp_messages",
        sa.Column("media_size_bytes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "whatsapp_messages",
        sa.Column("media_ciphertext", sa.Text(), nullable=True),
    )
    op.add_column(
        "whatsapp_messages",
        sa.Column("transcript_ciphertext", sa.Text(), nullable=True),
    )
    op.add_column(
        "whatsapp_messages",
        sa.Column("transcription_status", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "whatsapp_messages",
        sa.Column("transcription_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "whatsapp_messages",
        sa.Column("transcription_error", sa.String(length=500), nullable=True),
    )
    op.create_index(
        "ix_whatsapp_messages_next_delivery_at",
        "whatsapp_messages",
        ["next_delivery_at"],
    )
    op.create_index(
        "ix_whatsapp_messages_transcription_status",
        "whatsapp_messages",
        ["transcription_status"],
    )

    bind = op.get_bind()
    for table in ("whatsapp_gateway_health", "whatsapp_gateway_logs"):
        Base.metadata.tables[table].create(bind=bind, checkfirst=False)
        _tenant_policy(table)


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("whatsapp_gateway_logs", "whatsapp_gateway_health"):
        Base.metadata.tables[table].drop(bind=bind, checkfirst=False)
    op.drop_index("ix_whatsapp_messages_next_delivery_at", table_name="whatsapp_messages")
    op.drop_index("ix_whatsapp_messages_transcription_status", table_name="whatsapp_messages")
    for column in (
        "transcription_error",
        "transcription_attempts",
        "transcription_status",
        "transcript_ciphertext",
        "media_ciphertext",
        "media_size_bytes",
        "media_filename",
        "media_mime_type",
        "last_delivery_error",
        "next_delivery_at",
        "delivery_attempts",
    ):
        op.drop_column("whatsapp_messages", column)
