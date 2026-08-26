"""Financial analytics API contracts."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class AnalyticsMeta(BaseModel):
    date_from: date
    date_to: date
    branch_id: UUID | None
    data_as_of: datetime | None
    official_metric_codes: list[str] = Field(default_factory=list)
    is_reconciled: bool = False


class PnlResponse(BaseModel):
    revenue_accrual: Decimal
    revenue_payment: Decimal
    variable_expenses: Decimal
    fixed_expenses: Decimal
    uncategorized_expenses: Decimal
    payroll_accrual: Decimal
    total_expenses: Decimal
    gross_profit: Decimal
    ebitda: Decimal
    net_profit: Decimal
    expense_classification_rate: Decimal
    profit_is_complete: bool
    profit_label: str
    meta: AnalyticsMeta


class CashFlowResponse(BaseModel):
    inflow: Decimal
    outflow: Decimal
    net_cash_flow: Decimal
    closing_balance: Decimal | None
    cashflow_is_complete: bool = False
    meta: AnalyticsMeta


class FinanceSummaryResponse(BaseModel):
    revenue_accrual: Decimal
    revenue_payment: Decimal
    total_expenses: Decimal
    net_profit: Decimal
    net_cash_flow: Decimal
    closing_balance: Decimal | None
    cashflow_is_complete: bool = False
    meta: AnalyticsMeta
