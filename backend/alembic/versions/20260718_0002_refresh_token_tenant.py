"""Attach refresh sessions directly to a tenant for safe RLS bootstrap."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260718_0002"
down_revision: str | None = "20260718_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("refresh_tokens", sa.Column("tenant_id", postgresql.UUID(as_uuid=True)))
    op.execute(
        """UPDATE refresh_tokens AS token
           SET tenant_id = users.tenant_id
           FROM users
           WHERE users.id = token.user_id"""
    )
    op.alter_column("refresh_tokens", "tenant_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_refresh_tokens_tenant_id_tenants"),
        "refresh_tokens",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_refresh_tokens_tenant_id"), "refresh_tokens", ["tenant_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_refresh_tokens_tenant_id"), table_name="refresh_tokens")
    op.drop_constraint(op.f("fk_refresh_tokens_tenant_id_tenants"), "refresh_tokens", type_="foreignkey")
    op.drop_column("refresh_tokens", "tenant_id")
