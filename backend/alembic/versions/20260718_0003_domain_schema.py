"""Create the canonical domain schema and tenant isolation policies.

The legacy ORM-backed baseline is frozen in migration_schema/legacy_tables.json.
Later fields are owned by their additive revisions, not by current app.models.
"""

from collections.abc import Sequence

from alembic import op

from migration_schema import create_table as create_frozen_table, drop_table as drop_frozen_table

revision: str = "20260718_0003"
down_revision: str | None = "20260718_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DOMAIN_TABLES = (
    "doctors",
    "expense_categories",
    "integration_connections",
    "patients",
    "service_directions",
    "account_balances",
    "ai_insights",
    "appointments",
    "audit_log",
    "bank_statement_uploads",
    "doctor_compensation_rules",
    "doctor_ratings",
    "expense_facts",
    "leads",
    "marketing_spend_facts",
    "revenue_facts",
    "sync_runs",
    "treatment_plans",
    "ai_insight_reads",
    "attribution_facts",
    "calls",
    "raw_bank_transactions",
    "ai_classification_feedback",
    "cash_flow_facts",
)
RLS_EXCEPTIONS = {"ai_insight_reads"}


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    for table_name in DOMAIN_TABLES:
        create_frozen_table(revision, table_name, checkfirst=False)
    for table_name in DOMAIN_TABLES:
        if table_name in RLS_EXCEPTIONS:
            continue
        op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'''CREATE POLICY tenant_isolation ON "{table_name}"
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)'''
        )


def downgrade() -> None:
    for table_name in reversed(DOMAIN_TABLES):
        drop_frozen_table(table_name, checkfirst=False)
