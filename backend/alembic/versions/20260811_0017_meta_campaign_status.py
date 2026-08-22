"""Track the current Meta campaign delivery status.

Revision ID: 20260811_0017
Revises: 20260730_0016
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0017"
down_revision: str | None = "20260730_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = "meta_campaign_daily_metrics"
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns(table)}
    if "status" not in columns:
        op.add_column(table, sa.Column("status", sa.String(length=40), nullable=False, server_default="UNKNOWN"))
    if "effective_status" not in columns:
        op.add_column(table, sa.Column("effective_status", sa.String(length=40), nullable=False, server_default="UNKNOWN"))


def downgrade() -> None:
    op.drop_column("meta_campaign_daily_metrics", "effective_status")
    op.drop_column("meta_campaign_daily_metrics", "status")
