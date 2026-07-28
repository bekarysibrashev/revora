"""Add privacy-safe AI analyst conversations and audit metadata.

Revision ID: 20260727_0012
Revises: 20260727_0011
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260727_0012"
down_revision = "20260727_0011"
branch_labels = None
depends_on = None

TABLES = ("ai_chat_sessions", "ai_chat_messages", "ai_llm_call_audit")

def _tenant_policy(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(f'''CREATE POLICY tenant_isolation ON "{table}"
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)''')

def upgrade() -> None:
    op.create_table("ai_chat_sessions",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False), sa.Column("branch_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(200), nullable=False), sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"],["tenants.id"],ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"],["users.id"],ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["branch_id"],["branches.id"]), sa.PrimaryKeyConstraint("id"))
    op.create_table("ai_chat_messages",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False), sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("role", sa.String(20), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("tool_calls", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("model", sa.String(100), nullable=True), sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"],["tenants.id"],ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"],["ai_chat_sessions.id"],ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"],["users.id"],ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"))
    op.create_table("ai_llm_call_audit",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False), sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=False), sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False), sa.Column("status", sa.String(30), nullable=False),
        sa.Column("tool_names", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("input_characters", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_characters", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=True), sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True), sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"],["tenants.id"],ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"],["ai_chat_sessions.id"],ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"],["ai_chat_messages.id"],ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"],["users.id"],ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"))
    for table in TABLES:
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        _tenant_policy(table)
    op.create_index("ix_ai_chat_sessions_user_id", "ai_chat_sessions", ["user_id"])
    op.create_index("ix_ai_chat_sessions_last_message_at", "ai_chat_sessions", ["last_message_at"])
    op.create_index("ix_ai_chat_messages_session_id", "ai_chat_messages", ["session_id"])
    op.create_index("ix_ai_llm_call_audit_user_id", "ai_llm_call_audit", ["user_id"])

def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
