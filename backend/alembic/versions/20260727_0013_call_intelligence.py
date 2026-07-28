"""Turn call quality placeholders into an automatic privacy-safe report pipeline.

Revision ID: 20260727_0013
Revises: 20260727_0012
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260727_0013"
down_revision = "20260727_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("call_quality_analyses", "transcript")
    op.add_column("call_quality_analyses", sa.Column("strengths", postgresql.JSONB(), nullable=True))
    op.add_column("call_quality_analyses", sa.Column("flags", postgresql.JSONB(), nullable=True))
    op.add_column("call_quality_analyses", sa.Column("evidence", postgresql.JSONB(), nullable=True))
    op.add_column("call_quality_analyses", sa.Column("languages", postgresql.JSONB(), nullable=True))
    op.add_column("call_quality_analyses", sa.Column("mixed_language", sa.Boolean(), nullable=True))
    op.add_column("call_quality_analyses", sa.Column("operator_speaker", sa.String(30), nullable=True))
    op.add_column("call_quality_analyses", sa.Column("customer_speaker", sa.String(30), nullable=True))
    op.add_column("call_quality_analyses", sa.Column("confidence", sa.Numeric(4, 3), nullable=True))
    op.add_column("call_quality_analyses", sa.Column("needs_review", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("call_quality_analyses", sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("call_quality_analyses", sa.Column("error_code", sa.String(100), nullable=True))
    op.add_column("call_quality_analyses", sa.Column("error_message", sa.String(500), nullable=True))
    op.add_column("call_quality_analyses", sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("call_quality_analyses", sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("call_quality_analyses", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_call_quality_analyses_needs_review", "call_quality_analyses", ["needs_review"])


def downgrade() -> None:
    op.drop_index("ix_call_quality_analyses_needs_review", table_name="call_quality_analyses")
    for name in (
        "completed_at", "processing_started_at", "queued_at", "error_message",
        "error_code", "attempt_count", "needs_review", "confidence",
        "customer_speaker", "operator_speaker", "mixed_language", "languages",
        "evidence", "flags", "strengths",
    ):
        op.drop_column("call_quality_analyses", name)
    op.add_column("call_quality_analyses", sa.Column("transcript", sa.Text(), nullable=True))
