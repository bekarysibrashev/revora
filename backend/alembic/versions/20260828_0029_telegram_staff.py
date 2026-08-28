"""Add secure Telegram staff enrollment, task delivery and report schedules.

Revision ID: 20260828_0029
Revises: 20260828_0028
"""

from collections.abc import Sequence

from alembic import op

from app.core.database import Base
import app.models  # noqa: F401

revision: str = "20260828_0029"
down_revision: str | None = "20260828_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "telegram_invitations",
    "telegram_invite_routes",
    "telegram_employees",
    "telegram_employee_routes",
    "telegram_tasks",
    "telegram_report_subscriptions",
)
RLS_TABLES = (
    "telegram_invitations",
    "telegram_employees",
    "telegram_tasks",
    "telegram_report_subscriptions",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=False)
    for table_name in RLS_TABLES:
        op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'''CREATE POLICY tenant_isolation ON "{table_name}"
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)'''
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        Base.metadata.tables[table_name].drop(bind=bind, checkfirst=False)

