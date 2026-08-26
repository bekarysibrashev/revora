"""Ensure clinic owners have access to every branch.

Revision ID: 20260827_0022
Revises: 20260825_0021
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260827_0022"
down_revision: str | None = "20260825_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    tenant_ids = list(connection.execute(sa.text("SELECT id FROM tenants")).scalars())
    for tenant_id in tenant_ids:
        # users and branches use forced tenant RLS, so set the tenant for each
        # backfill statement instead of attempting a cross-tenant write.
        connection.execute(
            sa.text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO user_branches (user_id, branch_id, created_at, updated_at)
                SELECT users.id, branches.id, now(), now()
                FROM users
                CROSS JOIN branches
                WHERE users.tenant_id = :tenant_id
                  AND branches.tenant_id = :tenant_id
                  AND users.role = 'owner'
                  AND users.is_active = true
                ON CONFLICT (user_id, branch_id) DO NOTHING
                """
            ),
            {"tenant_id": tenant_id},
        )


def downgrade() -> None:
    # Access links may have existed before this migration and cannot be
    # distinguished safely, so downgrade intentionally preserves them.
    pass
