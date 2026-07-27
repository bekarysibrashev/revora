"""Expand Meta Ads campaign metrics.

Revision ID: 20260727_0011
Revises: 20260727_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260727_0011"
down_revision: str | None = "20260727_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = "meta_campaign_daily_metrics"
    for name in (
        "unique_clicks",
        "outbound_clicks",
        "landing_page_views",
        "leads",
        "purchases",
        "video_plays",
        "video_thruplays",
    ):
        op.add_column(
            table,
            sa.Column(name, sa.Integer(), nullable=False, server_default="0"),
        )
    for name in ("action_values", "outbound_clicks_raw"):
        op.add_column(
            table,
            sa.Column(
                name,
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )


def downgrade() -> None:
    table = "meta_campaign_daily_metrics"
    for name in (
        "outbound_clicks_raw",
        "action_values",
        "video_thruplays",
        "video_plays",
        "purchases",
        "leads",
        "landing_page_views",
        "outbound_clicks",
        "unique_clicks",
    ):
        op.drop_column(table, name)
