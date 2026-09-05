"""Financial analytics API contracts."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.reports.schemas import CoverageInfoResponse


class AnalyticsMeta(BaseModel):
    date_from: date
    date_to: date
    branch_id: UUID | None
    data_as_of: datetime | None
    official_metric_codes: list[str] = Field(default_factory=list)
    is_reconciled: bool = False
    coverage: dict[str, CoverageInfoResponse] = Field(default_factory=dict)


class PnlResponse(BaseModel):
    revenue_accrual: Decimal
    revenue_payment: Decimal
    variable_expenses: Decimal
    fixed_expenses: Decimal
    uncategorized_expenses: Decimal
    payroll_accrual: Decimal
    total_expenses: Decimal
    gross_profit: Decimal
    # Revenue minus classified operating costs (variable + fixed + payroll),
    # excluding not-yet-categorized expenses -- distinct from net_profit,
    # which subtracts every recognized expense including uncategorized ones.
    operating_profit: Decimal
    # Revora does not track depreciation/amortization, interest or tax as
    # their own ledgers, so EBITDA is computed equal to operating_profit
    # (the add-backs are assumed zero) rather than to net_profit, which
    # would wrongly fold in uncategorized/one-off items. See depends_on
    # in the /dashboard/cards CardStatus for this metric.
    ebitda: Decimal
    net_profit: Decimal
    expense_classification_rate: Decimal
    profit_is_complete: bool
    profit_label: str
    # None (never 0) when 1C has not sent this metric for the period.
    payroll_paid: Decimal | None = None
    operating_expenses: Decimal | None = None
    refunds: Decimal | None = None
    insurance_payments: Decimal | None = None
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
