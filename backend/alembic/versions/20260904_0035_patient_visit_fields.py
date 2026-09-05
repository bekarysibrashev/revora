"""Add visit/branch/active fields to patients, populated by the new 1C
patient_phone_identity snapshot (Task 1: full patient + phone_hash sync).

Revision ID: 20260904_0035
Revises: 20260903_0034

The patients table has existed since the initial domain schema
(20260718_0003) with external_id/full_name/phone_hash/phone_e164_encrypted,
but nothing has populated it since the old OData connector was retired.
This adds the remaining fields the 1C extension's new identity snapshot
needs to carry per patient: branch, first/last visit, visit count, and an
active/deleted flag -- everything ContactRegistry needs to classify an
inbound call/WhatsApp message against real 1C patients again.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260904_0035"
down_revision = "20260903_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_patients_branch_id", "patients", "branches", ["branch_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_patients_branch_id", "patients", ["branch_id"])
    op.add_column(
        "patients",
        sa.Column("first_visit_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "patients",
        sa.Column("last_visit_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "patients",
        sa.Column("visit_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "patients",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index("ix_patients_last_visit_at", "patients", ["last_visit_at"])


def downgrade() -> None:
    op.drop_index("ix_patients_last_visit_at", table_name="patients")
    op.drop_column("patients", "is_active")
    op.drop_column("patients", "visit_count")
    op.drop_column("patients", "last_visit_at")
    op.drop_column("patients", "first_visit_at")
    op.drop_index("ix_patients_branch_id", table_name="patients")
    op.drop_constraint("fk_patients_branch_id", "patients", type_="foreignkey")
    op.drop_column("patients", "branch_id")
