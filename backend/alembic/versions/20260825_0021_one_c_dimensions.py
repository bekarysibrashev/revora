"""Add the 1C dimensions required for exact operational analytics.

Revision ID: 20260825_0021
Revises: 20260820_0020
"""

from alembic import op
import sqlalchemy as sa


revision = "20260825_0021"
down_revision = "20260820_0020"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if "direction_id" not in _columns("revenue_facts"):
        op.add_column("revenue_facts", sa.Column("direction_id", sa.UUID(), nullable=True))
        op.create_foreign_key(
            "fk_revenue_facts_direction_id",
            "revenue_facts",
            "service_directions",
            ["direction_id"],
            ["id"],
        )
    if "ix_revenue_facts_direction_id" not in _indexes("revenue_facts"):
        op.create_index("ix_revenue_facts_direction_id", "revenue_facts", ["direction_id"])

    if "employee_id" not in _columns("payroll_facts"):
        op.add_column("payroll_facts", sa.Column("employee_id", sa.UUID(), nullable=True))
        op.create_foreign_key(
            "fk_payroll_facts_employee_id",
            "payroll_facts",
            "doctors",
            ["employee_id"],
            ["id"],
        )
    if "ix_payroll_facts_employee_id" not in _indexes("payroll_facts"):
        op.create_index("ix_payroll_facts_employee_id", "payroll_facts", ["employee_id"])

    if "account_ref" not in _columns("cash_flow_facts"):
        op.add_column(
            "cash_flow_facts",
            sa.Column("account_ref", sa.String(length=150), nullable=True),
        )
    if "ix_cash_flow_facts_account_ref" not in _indexes("cash_flow_facts"):
        op.create_index("ix_cash_flow_facts_account_ref", "cash_flow_facts", ["account_ref"])


def downgrade() -> None:
    op.drop_index("ix_cash_flow_facts_account_ref", table_name="cash_flow_facts")
    op.drop_column("cash_flow_facts", "account_ref")
    op.drop_index("ix_payroll_facts_employee_id", table_name="payroll_facts")
    op.drop_constraint("fk_payroll_facts_employee_id", "payroll_facts", type_="foreignkey")
    op.drop_column("payroll_facts", "employee_id")
    op.drop_index("ix_revenue_facts_direction_id", table_name="revenue_facts")
    op.drop_constraint("fk_revenue_facts_direction_id", "revenue_facts", type_="foreignkey")
    op.drop_column("revenue_facts", "direction_id")
