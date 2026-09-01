"""Release storage again by clearing the reproducible 1C ingest/audit layer.

Revision ID: 20260901_0032
Revises: 20260829_0031

The database reached 66.9% of its 1 GB free-tier storage limit. The bulk of
it is raw_records: 267k+ rows accumulated while ~212k of them sat quarantined
with ONE_C_PERIOD_MISSING (Document_Прием_Лечение and the two payment-line
entities), because the reprocess endpoint that would have resolved them was
timing out / getting OOM-killed on this hosting tier (see the two prior
commits fixing reset_one_c_records_for_reprocessing()). That reprocessing
path is now fixed, but the accumulated backlog itself is still the storage
problem, and there's no value in keeping quarantined rows around once the
connector can just re-push them correctly.

Same approach as 20260829_0031: TRUNCATE releases the relation files
immediately without needing extra working space, unlike row-by-row DELETE
which would need room to grow before it could shrink anything back.

Only the reproducible ingestion/audit layer is cleared. Tenant accounts,
branches, integration credentials, mapping profiles, official 1C reference
reports and canonical dashboard facts (revenue/cashflow/payroll/etc.) are
preserved untouched. The 1C system itself is never touched by this app --
the connector rebuilds raw_records from the live OData source on its next
sync.
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260901_0032"
down_revision: str | None = "20260829_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        TRUNCATE TABLE
            normalization_errors,
            record_lineage,
            raw_records,
            sync_runs
        """
    )


def downgrade() -> None:
    # The raw rows are reproducible from 1C; a downgrade cannot reconstruct
    # deleted source payloads and therefore deliberately performs no action.
    pass
