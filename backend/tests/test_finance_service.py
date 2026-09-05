from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.finance.repository import CashFlowTotals, PnlTotals
from app.modules.finance.service import FinanceService
from app.modules.reports.repository import CoverageInfo


class FakeFinanceRepository:
    async def pnl_totals(self, tenant_id, date_from, date_to, branch_id):
        return PnlTotals(
            revenue_accrual=Decimal("1000000"),
            revenue_payment=Decimal("900000"),
            variable_expenses=Decimal("250000"),
            fixed_expenses=Decimal("300000"),
            uncategorized_expenses=Decimal("50000"),
            payroll_accrual=Decimal("250000"),
            data_as_of=datetime(2026, 7, 20, 10, tzinfo=UTC),
        )

    async def cashflow_totals(self, tenant_id, date_from, date_to, branch_id):
        return CashFlowTotals(
            inflow=Decimal("950000"),
            outflow=Decimal("650000"),
            closing_balance=Decimal("1200000"),
            data_as_of=datetime(2026, 7, 20, 11, tzinfo=UTC),
        )


class FakeFinanceRepositoryFullCoverage:
    """A clinic whose revenue has full 1C coverage for the period and whose
    expenses are 100% classified -- the one case where profit_is_complete
    must flip to True instead of being permanently stuck at False.
    """

    async def pnl_totals(self, tenant_id, date_from, date_to, branch_id):
        return PnlTotals(
            revenue_accrual=Decimal("1000000"),
            revenue_payment=Decimal("900000"),
            variable_expenses=Decimal("250000"),
            fixed_expenses=Decimal("300000"),
            uncategorized_expenses=Decimal("0"),
            payroll_accrual=Decimal("250000"),
            data_as_of=datetime(2026, 7, 20, 10, tzinfo=UTC),
            coverage={
                "revenue_accrual": CoverageInfo(
                    requested_from=date(2026, 7, 1),
                    requested_to=date(2026, 7, 31),
                    covered_from=date(2026, 7, 1),
                    covered_to=date(2026, 7, 31),
                    is_exact=True,
                ),
            },
        )

    async def cashflow_totals(self, tenant_id, date_from, date_to, branch_id):
        return CashFlowTotals(
            inflow=Decimal("950000"),
            outflow=Decimal("650000"),
            closing_balance=Decimal("1200000"),
            data_as_of=datetime(2026, 7, 20, 11, tzinfo=UTC),
        )


def make_user(role: UserRole) -> User:
    return User(
        id=uuid4(),
        tenant_id=uuid4(),
        email=f"{role.value}@example.test",
        full_name="Finance User",
        password_hash="unused",
        role=role,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_finance_summary_calculates_profit_and_cashflow() -> None:
    service = FinanceService(FakeFinanceRepository())

    response = await service.summary(
        make_user(UserRole.OWNER), date(2026, 7, 1), date(2026, 7, 31), None
    )

    assert response.total_expenses == Decimal("600000")
    assert response.net_profit == Decimal("400000")
    assert response.net_cash_flow == Decimal("300000")
    assert response.closing_balance == Decimal("1200000")
    assert response.meta.data_as_of == datetime(2026, 7, 20, 11, tzinfo=UTC)


@pytest.mark.asyncio
async def test_partial_expense_classification_is_not_called_net_profit() -> None:
    response = await FinanceService(FakeFinanceRepository()).pnl(
        make_user(UserRole.OWNER), date(2026, 7, 1), date(2026, 7, 31), None
    )

    assert response.expense_classification_rate == Decimal("550000") / Decimal("600000")
    assert response.profit_is_complete is False
    assert response.profit_label == "Операционная прибыль по доступным данным"


@pytest.mark.asyncio
async def test_finance_rejects_operational_roles() -> None:
    service = FinanceService(FakeFinanceRepository())

    with pytest.raises(AppError) as error:
        await service.pnl(
            make_user(UserRole.ADMINISTRATOR),
            date(2026, 7, 1),
            date(2026, 7, 31),
            None,
        )

    assert error.value.code == "FORBIDDEN"


@pytest.mark.asyncio
async def test_finance_rejects_reversed_date_range() -> None:
    service = FinanceService(FakeFinanceRepository())

    with pytest.raises(AppError) as error:
        await service.pnl(
            make_user(UserRole.OWNER),
            date(2026, 8, 1),
            date(2026, 7, 1),
            None,
        )

    assert error.value.code == "INVALID_DATE_RANGE"


@pytest.mark.asyncio
async def test_ebitda_is_operating_profit_not_an_alias_of_net_profit() -> None:
    response = await FinanceService(FakeFinanceRepository()).pnl(
        make_user(UserRole.OWNER), date(2026, 7, 1), date(2026, 7, 31), None
    )

    # operating_profit excludes uncategorized_expenses (50000, not yet
    # attributed to a real cost line); net_profit deducts it. They must
    # differ, and ebitda must track operating_profit, not net_profit.
    assert response.operating_profit == Decimal("200000")
    assert response.net_profit == Decimal("400000")
    assert response.ebitda == response.operating_profit
    assert response.ebitda != response.net_profit


@pytest.mark.asyncio
async def test_profit_is_complete_when_revenue_has_full_coverage_and_no_uncategorized() -> None:
    response = await FinanceService(FakeFinanceRepositoryFullCoverage()).pnl(
        make_user(UserRole.OWNER), date(2026, 7, 1), date(2026, 7, 31), None
    )

    assert response.profit_is_complete is True
    assert response.profit_label == "Чистая прибыль"
    assert response.operating_profit == Decimal("1000000") - Decimal("250000") - Decimal("300000") - Decimal("250000")
    assert response.ebitda == response.operating_profit
