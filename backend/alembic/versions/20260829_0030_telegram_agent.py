"""Link Telegram leaders to Revora users and add confirmed AI task drafts.

Revision ID: 20260829_0030
Revises: 20260828_0029
"""

from collections.abc import Sequence

from alembic import op

from app.core.database import Base
import app.models  # noqa: F401

revision: str = "20260829_0030"
down_revision: str | None = "20260828_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """ALTER TABLE telegram_invitations
           ADD COLUMN IF NOT EXISTS linked_user_id uuid
           REFERENCES users(id) ON DELETE CASCADE"""
    )
    op.execute(
        """ALTER TABLE telegram_employees
           ADD COLUMN IF NOT EXISTS linked_user_id uuid
           REFERENCES users(id) ON DELETE SET NULL"""
    )
    op.execute(
        """ALTER TABLE telegram_employees
           ADD COLUMN IF NOT EXISTS agent_session_id uuid
           REFERENCES ai_chat_sessions(id) ON DELETE SET NULL"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_telegram_invitations_linked_user_id "
        "ON telegram_invitations (linked_user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_telegram_employees_linked_user_id "
        "ON telegram_employees (linked_user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_telegram_employees_agent_session_id "
        "ON telegram_employees (agent_session_id)"
    )
    op.execute(
        """DO $$ BEGIN
             IF NOT EXISTS (
               SELECT 1 FROM pg_constraint
               WHERE conname = 'uq_telegram_employee_linked_user'
             ) THEN
               ALTER TABLE telegram_employees
               ADD CONSTRAINT uq_telegram_employee_linked_user
               UNIQUE (tenant_id, linked_user_id);
             END IF;
           END $$"""
    )

    table_name = "telegram_agent_task_drafts"
    Base.metadata.tables[table_name].create(bind=op.get_bind(), checkfirst=True)
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'''DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = '{table_name}' AND policyname = 'tenant_isolation'
              ) THEN
                CREATE POLICY tenant_isolation ON "{table_name}"
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
              END IF;
            END $$'''
    )


def downgrade() -> None:
    Base.metadata.tables["telegram_agent_task_drafts"].drop(
        bind=op.get_bind(), checkfirst=True
    )
    op.execute(
        "ALTER TABLE telegram_employees DROP CONSTRAINT IF EXISTS "
        "uq_telegram_employee_linked_user"
    )
    op.execute("ALTER TABLE telegram_employees DROP COLUMN IF EXISTS agent_session_id")
    op.execute("ALTER TABLE telegram_employees DROP COLUMN IF EXISTS linked_user_id")
    op.execute("ALTER TABLE telegram_invitations DROP COLUMN IF EXISTS linked_user_id")
