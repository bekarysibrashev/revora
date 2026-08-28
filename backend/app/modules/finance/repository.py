"""Aggregate financial facts without applying presentation policy."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.models import (
    AccountBalance,
    CashFlowFact,
    ExpenseCategory,
    ExpenseFact,
    PayrollFact,
    RevenueFact,
)
from app.shared.timezone import clinic_day_end_exclusive, clinic_day_start
from app.modules.reports.repository import OfficialReportsRepository

ZERO = Decimal("0")


@dataclass(frozen=True)
class PnlTotals:
    revenue_accrual: Decimal
    revenue_payment: Decimal
    variable_expenses: Decimal
    fixed_expenses: Decimal
    uncategorized_expenses: Decimal
    payroll_accrual: Decimal
    data_as_of: datetime | None
    official_metrics: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class CashFlowTotals:
    inflow: Decimal
    outflow: Decimal
    closing_balance: Decimal | None
    data_as_of: datetime | None
    official_metrics: frozenset[str] = field(default_factory=frozenset)
    cashflow_is_complete: bool = False


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
        payroll_statement = select(
            func.coalesce(func.sum(PayrollFact.amount), 0),
            func.max(PayrollFact.updated_at),
        ).where(
            PayrollFact.tenant_id == tenant_id,
            PayrollFact.occurred_on >= date_from,
            PayrollFact.occurred_on <= date_to,
        )
        if branch_id:
            payroll_statement = payroll_statement.where(PayrollFact.branch_id == branch_id)
        payroll = (await self.session.execute(payroll_statement)).one()
        timestamps = [value for value in (revenue[2], expense[3], payroll[1]) if value is not None]
        official, official_as_of = await OfficialReportsRepository(self.session).exact_values(
            tenant_id,
            date_from,
            date_to,
            {"revenue_accrual", "revenue_payment", "payroll_accrual"},
            [branch_id] if branch_id else None,
        )
        if official_as_of:
            timestamps.append(official_as_of)
        return PnlTotals(
            revenue_accrual=official.get("revenue_accrual", Decimal(revenue[0])),
            revenue_payment=official.get("revenue_payment", Decimal(revenue[1])),
            variable_expenses=Decimal(expense[0]),
            fixed_expenses=Decimal(expense[1]),
            uncategorized_expenses=Decimal(expense[2]),
            payroll_accrual=official.get("payroll_accrual", Decimal(payroll[0])),
            data_as_of=max(timestamps) if timestamps else None,
            official_metrics=frozenset(official),
        )

    async def cashflow_totals(
        self, tenant_id: UUID, date_from: date, date_to: date, branch_id: UUID | None
    ) -> CashFlowTotals:
        # Gross movements from the 1C money register contain transfers between
        # the clinic's own cash boxes and bank accounts. For management cash
        # flow, use the same patient-payment source as the official receipts
        # report and only known paid purchase/payroll documents as outflow.
        statement = select(
            func.coalesce(func.sum(RevenueFact.amount), 0),
            func.max(RevenueFact.updated_at),
        ).where(
            RevenueFact.tenant_id == tenant_id,
            RevenueFact.recognition_type == "payment",
            RevenueFact.occurred_at >= self._start(date_from),
            RevenueFact.occurred_at < self._end_exclusive(date_to),
        )
        if branch_id:
            statement = statement.where(RevenueFact.branch_id == branch_id)
        row = (await self.session.execute(statement)).one()

        expense_paid_statement = select(
            func.coalesce(func.sum(ExpenseFact.paid_amount), 0),
            func.max(ExpenseFact.updated_at),
        ).where(
            ExpenseFact.tenant_id == tenant_id,
            ExpenseFact.occurred_on >= date_from,
            ExpenseFact.occurred_on <= date_to,
        )
        payroll_paid_statement = select(
            func.coalesce(func.sum(PayrollFact.paid_amount), 0),
            func.max(PayrollFact.updated_at),
        ).where(
            PayrollFact.tenant_id == tenant_id,
            PayrollFact.occurred_on >= date_from,
            PayrollFact.occurred_on <= date_to,
        )
        if branch_id:
            expense_paid_statement = expense_paid_statement.where(ExpenseFact.branch_id == branch_id)
            payroll_paid_statement = payroll_paid_statement.where(PayrollFact.branch_id == branch_id)
        expense_paid = (await self.session.execute(expense_paid_statement)).one()
        payroll_paid = (await self.session.execute(payroll_paid_statement)).one()

        latest_balance = (
            select(
                AccountBalance.account_ref.label("account_ref"),
                AccountBalance.branch_id.label("branch_id"),
                func.max(AccountBalance.balance_at).label("balance_at"),
            )
            .where(
                AccountBalance.tenant_id == tenant_id,
                AccountBalance.balance_at < self._end_exclusive(date_to),
            )
            .group_by(AccountBalance.account_ref, AccountBalance.branch_id)
        )
        if branch_id:
            latest_balance = latest_balance.where(AccountBalance.branch_id == branch_id)
        latest_balance = latest_balance.subquery()
        balance_statement = (
            select(
                func.sum(AccountBalance.amount),
                func.max(AccountBalance.updated_at),
            )
            .join(
                latest_balance,
                (latest_balance.c.account_ref == AccountBalance.account_ref)
                & (latest_balance.c.balance_at == AccountBalance.balance_at)
                & (latest_balance.c.branch_id.is_not_distinct_from(AccountBalance.branch_id)),
            )
            .where(AccountBalance.tenant_id == tenant_id)
        )
        balance = (await self.session.execute(balance_statement)).one()
        closing_balance = Decimal(balance[0]) if balance[0] is not None else None

        timestamps = [
            value
            for value in (row[1], expense_paid[1], payroll_paid[1], balance[1])
            if value is not None
        ]
        official, official_as_of = await OfficialReportsRepository(self.session).exact_values(
            tenant_id,
            date_from,
            date_to,
            {"cash_inflow", "purchases_paid", "payroll_paid"},
            [branch_id] if branch_id else None,
        )
        if official_as_of:
            timestamps.append(official_as_of)
        inflow = official.get("cash_inflow", Decimal(row[0]))
        has_known_outflow = {"purchases_paid", "payroll_paid"}.issubset(official)
        outflow = (
            official["purchases_paid"] + official["payroll_paid"]
            if has_known_outflow
            else Decimal(expense_paid[0]) + Decimal(payroll_paid[0])
        )
        return CashFlowTotals(
            inflow=inflow,
            outflow=outflow,
            closing_balance=closing_balance,
            data_as_of=max(timestamps) if timestamps else None,
            official_metrics=frozenset(official),
            cashflow_is_complete=False,
        )

    @staticmethod
    def _start(value: date) -> datetime:
        return clinic_day_start(value)

    @staticmethod
    def _end_exclusive(value: date) -> datetime:
        return clinic_day_end_exclusive(value)
