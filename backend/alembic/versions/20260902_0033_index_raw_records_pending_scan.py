"""Speed up the background normalization worker's pending-batch query.

Revision ID: 20260902_0033
Revises: 20260901_0032

normalize_one_c_background_batch() pulls the next 200 pending raw_records
via:

    WHERE tenant_id=... AND connection_id=... AND source_entity IN (...)
          AND status='pending' AND <JSONB date filter>
    ORDER BY <dependency CASE>, received_at, id
    LIMIT 200
    FOR UPDATE SKIP LOCKED

raw_records only has single-column indexes on tenant_id, connection_id,
source_entity, status and received_at individually -- no composite index
backs this combined filter. With ~92k rows and a growing pending backlog
(~28k as of this migration), Postgres has to fall back to scanning and
filtering a large share of the table on every single batch call, which is
the same "worked fine at test scale, fell over at real scale" pattern that
caused the OOM crash fixed in 73b47c3, except here it manifests as a query
slow enough (tens of minutes on the free-tier instance) that the embedded
worker looked completely stuck rather than crashing outright.

This index lets Postgres jump straight to the candidate rows for a given
tenant/connection/status instead of scanning the table, which is the
dominant cost -- the dependency-order CASE in ORDER BY still requires an
in-memory sort of the matching rows, but that set shrinks from "most of
raw_records" to "this connection's pending rows", which is the actual
target of a single batch.

Purely additive: no data is touched, nothing is removed, safe to run
against a live table (CONCURRENTLY, outside the migration's transaction).
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260902_0033"
down_revision: str | None = "20260901_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS
                ix_raw_records_pending_batch_scan
            ON raw_records (tenant_id, connection_id, status, source_entity)
            WHERE status = 'pending'
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_raw_records_pending_batch_scan"
        )
