"""Track Meta Ads synchronization attempts separately from successful loads.

Revision ID: 20260816_0019
Revises: 20260815_0018
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260816_0019"
down_revision: str | None = "20260815_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"] for column in inspector.get_columns("meta_ads_accounts")
    }
    if "last_sync_attempted_at" not in columns:
        op.add_column(
            "meta_ads_accounts",
            sa.Column("last_sync_attempted_at", sa.DateTime(timezone=True), nullable=True),
        )
    op.execute(
        "UPDATE meta_ads_accounts "
        "SET last_sync_attempted_at = last_synced_at "
        "WHERE last_synced_at IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("meta_ads_accounts", "last_sync_attempted_at")
