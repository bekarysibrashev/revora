"""Create the canonical domain schema and tenant isolation policies.

This initial domain revision intentionally creates the registered table snapshots
through SQLAlchemy so PostgreSQL-specific exclusion constraints and indexes use
the exact same definitions as the ORM. Once deployed, this revision is immutable.
"""

from collections.abc import Sequence

from alembic import op

from app.core.database import Base
import app.models  # noqa: F401

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
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    for table_name in DOMAIN_TABLES:
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=False)
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
    bind = op.get_bind()
    for table_name in reversed(DOMAIN_TABLES):
        Base.metadata.tables[table_name].drop(bind=bind, checkfirst=False)
