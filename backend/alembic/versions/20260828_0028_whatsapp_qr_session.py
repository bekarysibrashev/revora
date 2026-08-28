"""Persist encrypted WhatsApp QR gateway sessions.

Revision ID: 20260828_0028
Revises: 20260828_0027
"""
from collections.abc import Sequence

from alembic import op

from app.core.database import Base
import app.models  # noqa: F401

revision: str = "20260828_0028"
down_revision: str | None = "20260828_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = "whatsapp_qr_sessions"
    bind = op.get_bind()
    Base.metadata.tables[table].create(bind=bind, checkfirst=False)
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'''CREATE POLICY tenant_isolation ON "{table}"
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)'''
    )


def downgrade() -> None:
    Base.metadata.tables["whatsapp_qr_sessions"].drop(
        bind=op.get_bind(), checkfirst=False
    )
