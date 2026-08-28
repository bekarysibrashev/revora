"""Add fields required for exact 1C OData reconciliation.

Revision ID: 20260828_0026
Revises: 20260828_0025
"""

from alembic import op
import sqlalchemy as sa


revision = "20260828_0026"
down_revision = "20260828_0025"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "has_reception" not in _columns("appointments"):
        op.add_column(
            "appointments",
            sa.Column("has_reception", sa.Boolean(), server_default=sa.false(), nullable=False),
        )
        op.create_index("ix_appointments_has_reception", "appointments", ["has_reception"])
    if "patient_id" in _columns("appointments"):
        op.alter_column("appointments", "patient_id", existing_type=sa.UUID(), nullable=True)
    if "paid_amount" not in _columns("expense_facts"):
        op.add_column(
            "expense_facts",
            sa.Column("paid_amount", sa.Numeric(14, 2), server_default="0", nullable=False),
        )
    if "paid_amount" not in _columns("payroll_facts"):
        op.add_column(
            "payroll_facts",
            sa.Column("paid_amount", sa.Numeric(14, 2), server_default="0", nullable=False),
        )


def downgrade() -> None:
    op.drop_column("payroll_facts", "paid_amount")
    op.drop_column("expense_facts", "paid_amount")
    op.alter_column("appointments", "patient_id", existing_type=sa.UUID(), nullable=False)
    op.drop_index("ix_appointments_has_reception", table_name="appointments")
    op.drop_column("appointments", "has_reception")
