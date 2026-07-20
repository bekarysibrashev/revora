from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.finance.repository import CashFlowTotals, PnlTotals
from app.modules.finance.service import FinanceService


class FakeFinanceRepository:
    async def pnl_totals(self, tenant_id, date_from, date_to, branch_id):
        return PnlTotals(
            revenue_accrual=Decimal("1000000"),
            revenue_payment=Decimal("900000"),
            variable_expenses=Decimal("250000"),
            fixed_expenses=Decimal("300000"),
            uncategorized_expenses=Decimal("50000"),
            data_as_of=datetime(2026, 7, 20, 10, tzinfo=UTC),
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
