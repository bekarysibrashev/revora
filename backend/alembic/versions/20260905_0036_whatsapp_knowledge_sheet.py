"""Persist one connected Google Sheet per tenant for WhatsApp knowledge sync.

Revision ID: 20260905_0036
Revises: 20260904_0035

The owner pastes a link to their scripts spreadsheet (shared read-only with
Revora's Google service account); a Celery beat job re-imports it on a
schedule, reusing the same XLSX parser as the manual upload, and a
"Sync now" button re-runs it on demand. This table only remembers which
sheet is connected and the outcome of the last sync -- it never stores
sheet content, that always lands in whatsapp_knowledge_items.
"""
from collections.abc import Sequence

from alembic import op

from app.core.database import Base
import app.models  # noqa: F401

revision: str = "20260905_0036"
down_revision: str | None = "20260904_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = "whatsapp_knowledge_sheets"
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
    Base.metadata.tables["whatsapp_knowledge_sheets"].drop(
        bind=op.get_bind(), checkfirst=False
    )
