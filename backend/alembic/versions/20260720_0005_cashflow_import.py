"""Allow source-agnostic cash flow facts.

Revision ID: 20260720_0005
Revises: 20260720_0004
"""
from alembic import op
import sqlalchemy as sa

revision = "20260720_0005"
down_revision = "20260720_0004"
branch_labels = None
depends_on = None

def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"]: column for column in inspector.get_columns("cash_flow_facts")}
    if "external_id" not in columns:
        op.add_column("cash_flow_facts", sa.Column("external_id", sa.String(length=150), nullable=True))
    if not columns["raw_transaction_id"]["nullable"]:
        op.alter_column("cash_flow_facts", "raw_transaction_id", existing_type=sa.UUID(), nullable=True)
    unique_column_sets = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("cash_flow_facts")
    }
    if ("tenant_id", "external_id") not in unique_column_sets:
        op.create_unique_constraint("uq_cash_flow_facts_tenant_external_id", "cash_flow_facts", ["tenant_id", "external_id"])

def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    unique_names = {constraint["name"] for constraint in inspector.get_unique_constraints("cash_flow_facts")}
    if "uq_cash_flow_facts_tenant_external_id" in unique_names:
        op.drop_constraint("uq_cash_flow_facts_tenant_external_id", "cash_flow_facts", type_="unique")
    op.alter_column("cash_flow_facts", "raw_transaction_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("cash_flow_facts", "external_id")
