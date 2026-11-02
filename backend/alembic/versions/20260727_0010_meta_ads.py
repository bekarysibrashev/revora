"""Add Meta Ads account and daily campaign metrics.

Revision ID: 20260727_0010
Revises: 20260726_0009
"""

from collections.abc import Sequence

from alembic import op

from migration_schema import create_table as create_frozen_table, drop_table as drop_frozen_table

revision: str = "20260727_0010"
down_revision: str | None = "20260726_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("meta_ads_accounts", "meta_campaign_daily_metrics")


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
