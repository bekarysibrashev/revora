"""Add WhatsApp AI assistant.

Revision ID: 20260729_0014
Revises: 20260727_0013
"""
from collections.abc import Sequence

from alembic import op

from migration_schema import create_table as create_frozen_table, drop_table as drop_frozen_table

revision: str = "20260729_0014"
down_revision: str | None = "20260727_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "whatsapp_channels",
    "whatsapp_conversations",
    "whatsapp_messages",
    "whatsapp_knowledge_items",
    "whatsapp_ai_usage",
)


def upgrade() -> None:
    for table_name in TABLES:
        create_frozen_table(revision, table_name, checkfirst=False)
        op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'''CREATE POLICY tenant_isolation ON "{table_name}"
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)'''
        )


def downgrade() -> None:
    for table_name in reversed(TABLES):
        drop_frozen_table(table_name, checkfirst=False)
