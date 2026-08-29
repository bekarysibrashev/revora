"""Release storage consumed by the accidental full OData import.

Revision ID: 20260829_0031
Revises: 20260829_0030

The clinic connector temporarily uploaded every published OData entity and
every scalar property.  On the free PostgreSQL instance that exhausted the
database before a normal cleanup request could even be recorded.  TRUNCATE is
intentional here: unlike row-by-row DELETE it releases the relation files
immediately and does not require extra working space.

Only the reproducible ingestion/audit layer is cleared.  Tenant accounts,
branches, integration credentials, mapping profiles, official 1C reference
reports and canonical dashboard facts are preserved.  The connector can
rebuild the cleared rows from the read-only 1C OData source.
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260829_0031"
down_revision: str | None = "20260829_0030"
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
