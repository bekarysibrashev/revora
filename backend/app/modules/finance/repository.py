"""Aggregate financial facts without applying presentation policy."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.models import (
    AccountBalance,
    CashFlowFact,
    ExpenseCategory,
    ExpenseFact,
    RevenueFact,
)

ZERO = Decimal("0")


@dataclass(frozen=True)
class PnlTotals:
    revenue_accrual: Decimal
    revenue_payment: Decimal
    variable_expenses: Decimal
    fixed_expenses: Decimal
    uncategorized_expenses: Decimal
    data_as_of: datetime | None


@dataclass(frozen=True)
class CashFlowTotals:
    inflow: Decimal
    outflow: Decimal
    closing_balance: Decimal | None
    data_as_of: datetime | None


class FinanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def pnl_totals(
        self, tenant_id: UUID, date_from: date, date_to: date, branch_id: UUID | None
    ) -> PnlTotals:
        revenue_statement = select(
            func.coalesce(
                func.sum(
                    case((RevenueFact.recognition_type == "accrual", RevenueFact.amount), else_=0)
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case((RevenueFact.recognition_type == "payment", RevenueFact.amount), else_=0)
                ),
                0,
            ),
            func.max(RevenueFact.occurred_at),
        ).where(
            RevenueFact.tenant_id == tenant_id,
            RevenueFact.occurred_at >= self._start(date_from),
            RevenueFact.occurred_at < self._end_exclusive(date_to),
        )
        if branch_id:
            revenue_statement = revenue_statement.where(RevenueFact.branch_id == branch_id)
        revenue = (await self.session.execute(revenue_statement)).one()

        expense_statement = (
            select(
                func.coalesce(
                    func.sum(
                        case((ExpenseCategory.cost_behavior == "variable", ExpenseFact.amount), else_=0)
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case((ExpenseCategory.cost_behavior == "fixed", ExpenseFact.amount), else_=0)
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (ExpenseFact.category_id.is_(None))
                                | (ExpenseCategory.cost_behavior.is_(None)),
                                ExpenseFact.amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.max(ExpenseFact.updated_at),
            )
            .select_from(ExpenseFact)
            .outerjoin(ExpenseCategory, ExpenseCategory.id == ExpenseFact.category_id)
            .where(
                ExpenseFact.tenant_id == tenant_id,
                ExpenseFact.occurred_on >= date_from,
                ExpenseFact.occurred_on <= date_to,
            )
        )
        if branch_id:
            expense_statement = expense_statement.where(ExpenseFact.branch_id == branch_id)
        expense = (await self.session.execute(expense_statement)).one()
        timestamps = [value for value in (revenue[2], expense[3]) if value is not None]
        return PnlTotals(
            revenue_accrual=Decimal(revenue[0]),
            revenue_payment=Decimal(revenue[1]),
            variable_expenses=Decimal(expense[0]),
            fixed_expenses=Decimal(expense[1]),
            uncategorized_expenses=Decimal(expense[2]),
            data_as_of=max(timestamps) if timestamps else None,
        )

    async def cashflow_totals(
        self, tenant_id: UUID, date_from: date, date_to: date, branch_id: UUID | None
    ) -> CashFlowTotals:
        statement = select(
            func.coalesce(
                func.sum(case((CashFlowFact.direction == "in", CashFlowFact.amount), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((CashFlowFact.direction == "out", CashFlowFact.amount), else_=0)), 0
            ),
            func.max(CashFlowFact.updated_at),
        ).where(
            CashFlowFact.tenant_id == tenant_id,
            CashFlowFact.occurred_at >= self._start(date_from),
            CashFlowFact.occurred_at < self._end_exclusive(date_to),
        )
        if branch_id:
            statement = statement.where(CashFlowFact.branch_id == branch_id)
        row = (await self.session.execute(statement)).one()

        balance_statement = (
            select(AccountBalance.amount, AccountBalance.updated_at)
            .where(
                AccountBalance.tenant_id == tenant_id,
                AccountBalance.balance_at < self._end_exclusive(date_to),
            )
            .order_by(AccountBalance.balance_at.desc())
            .limit(1)
        )
        if branch_id:
            balance_statement = balance_statement.where(AccountBalance.branch_id == branch_id)
        balance = (await self.session.execute(balance_statement)).first()
        timestamps = [value for value in (row[2], balance[1] if balance else None) if value is not None]
        return CashFlowTotals(
            inflow=Decimal(row[0]),
            outflow=Decimal(row[1]),
            closing_balance=Decimal(balance[0]) if balance else None,
            data_as_of=max(timestamps) if timestamps else None,
        )

    @staticmethod
    def _start(value: date) -> datetime:
        return datetime.combine(value, time.min, tzinfo=timezone.utc)

    @staticmethod
    def _end_exclusive(value: date) -> datetime:
        return datetime.combine(value + timedelta(days=1), time.min, tzinfo=timezone.utc)
