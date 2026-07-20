"""Create core tenancy and authentication tables."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260718_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_role = postgresql.ENUM(
    "owner", "manager", "administrator", "sales_manager", name="user_role", create_type=False
)


def upgrade() -> None:
    user_role.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "tenants",
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("timezone", sa.String(50), server_default="Asia/Almaty", nullable=False),
        sa.Column("currency", sa.String(3), server_default="KZT", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenants_slug")),
    )
    op.create_table(
        "branches",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("address", sa.String(500)),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE", name=op.f("fk_branches_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_branches")),
        sa.UniqueConstraint("tenant_id", "code", name=op.f("uq_branches_tenant_id")),
    )
    op.create_index(op.f("ix_branches_tenant_id"), "branches", ["tenant_id"])
    op.create_table(
        "users",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE", name=op.f("fk_users_tenant_id_tenants")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("tenant_id", "email", name=op.f("uq_users_tenant_id")),
    )
    op.create_index(op.f("ix_users_tenant_id"), "users", ["tenant_id"])
    op.create_table(
        "user_branches",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE", name=op.f("fk_user_branches_branch_id_branches")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_user_branches_user_id_users")),
        sa.PrimaryKeyConstraint("user_id", "branch_id", name=op.f("pk_user_branches")),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("replaced_by_id", postgresql.UUID(as_uuid=True)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["replaced_by_id"], ["refresh_tokens.id"], ondelete="SET NULL", name=op.f("fk_refresh_tokens_replaced_by_id_refresh_tokens")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_refresh_tokens_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(op.f("ix_refresh_tokens_expires_at"), "refresh_tokens", ["expires_at"])
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"])

    for table in ("branches", "users"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'''CREATE POLICY tenant_isolation ON "{table}"
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)'''
        )


def downgrade() -> None:
    op.drop_table("refresh_tokens")
    op.drop_table("user_branches")
    op.drop_table("users")
    op.drop_table("branches")
    op.drop_table("tenants")
    user_role.drop(op.get_bind(), checkfirst=True)
