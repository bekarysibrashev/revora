"""Role-aware financial analytics use cases."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.finance.repository import FinanceRepository
from app.modules.finance.schemas import (
    AnalyticsMeta,
    CashFlowResponse,
    FinanceSummaryResponse,
    PnlResponse,
)


class FinanceService:
    def __init__(self, repository: FinanceRepository) -> None:
        self.repository = repository

    async def pnl(
        self, user: User, date_from: date, date_to: date, branch_id: UUID | None
    ) -> PnlResponse:
        self._validate(user, date_from, date_to, branch_id)
        totals = await self.repository.pnl_totals(user.tenant_id, date_from, date_to, branch_id)
        total_expenses = (
            totals.variable_expenses + totals.fixed_expenses + totals.uncategorized_expenses
        )
        gross_profit = totals.revenue_accrual - totals.variable_expenses
        net_profit = totals.revenue_accrual - total_expenses
        return PnlResponse(
            revenue_accrual=totals.revenue_accrual,
            revenue_payment=totals.revenue_payment,
            variable_expenses=totals.variable_expenses,
            fixed_expenses=totals.fixed_expenses,
            uncategorized_expenses=totals.uncategorized_expenses,
            total_expenses=total_expenses,
            gross_profit=gross_profit,
            ebitda=net_profit,
            net_profit=net_profit,
            meta=AnalyticsMeta(
                date_from=date_from,
                date_to=date_to,
                branch_id=branch_id,
                data_as_of=totals.data_as_of,
            ),
        )

    async def cashflow(
        self, user: User, date_from: date, date_to: date, branch_id: UUID | None
    ) -> CashFlowResponse:
        self._validate(user, date_from, date_to, branch_id)
        totals = await self.repository.cashflow_totals(
            user.tenant_id, date_from, date_to, branch_id
        )
        return CashFlowResponse(
            inflow=totals.inflow,
            outflow=totals.outflow,
            net_cash_flow=totals.inflow - totals.outflow,
            closing_balance=totals.closing_balance,
            meta=AnalyticsMeta(
                date_from=date_from,
                date_to=date_to,
                branch_id=branch_id,
                data_as_of=totals.data_as_of,
            ),
        )

    async def summary(
        self, user: User, date_from: date, date_to: date, branch_id: UUID | None
    ) -> FinanceSummaryResponse:
        pnl = await self.pnl(user, date_from, date_to, branch_id)
        cashflow = await self.cashflow(user, date_from, date_to, branch_id)
        timestamps = [item for item in (pnl.meta.data_as_of, cashflow.meta.data_as_of) if item]
        return FinanceSummaryResponse(
            revenue_accrual=pnl.revenue_accrual,
            revenue_payment=pnl.revenue_payment,
            total_expenses=pnl.total_expenses,
            net_profit=pnl.net_profit,
            net_cash_flow=cashflow.net_cash_flow,
            closing_balance=cashflow.closing_balance,
            meta=AnalyticsMeta(
                date_from=date_from,
                date_to=date_to,
                branch_id=branch_id,
                data_as_of=max(timestamps) if timestamps else None,
            ),
        )

    @staticmethod
    def _validate(user: User, date_from: date, date_to: date, branch_id: UUID | None) -> None:
        if user.role not in {UserRole.OWNER, UserRole.MANAGER}:
            raise AppError("FORBIDDEN", "Financial analytics are not available for this role", 403)
        if date_from > date_to:
            raise AppError("INVALID_DATE_RANGE", "date_from must not be after date_to", 422)
        if (date_to - date_from).days > 1095:
            raise AppError("DATE_RANGE_TOO_LARGE", "Date range cannot exceed three years", 422)
        if branch_id is not None and user.branch_links:
            allowed = {link.branch_id for link in user.branch_links}
            if branch_id not in allowed:
                raise AppError("BRANCH_FORBIDDEN", "Branch is outside your access scope", 403)
