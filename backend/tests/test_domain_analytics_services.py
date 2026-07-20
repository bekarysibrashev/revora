from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.modules.auth.models import User, UserBranch, UserRole
from app.modules.doctors.repository import DoctorTotals
from app.modules.doctors.service import DoctorsService
from app.modules.marketing.repository import MarketingTotals
from app.modules.marketing.service import MarketingService
from app.modules.sales.repository import SalesTotals
from app.modules.sales.service import SalesService


def make_user(role: UserRole, branch_id=None) -> User:
    user = User(
        id=uuid4(),
        tenant_id=uuid4(),
        email=f"{role.value}@example.test",
        full_name="Analytics User",
        password_hash="unused",
        role=role,
        is_active=True,
    )
    user.branch_links = (
        [UserBranch(user_id=user.id, branch_id=branch_id)] if branch_id else []
    )
    return user


class FakeSalesRepository:
    def __init__(self):
        self.scope = None

    async def overview(self, tenant_id, date_from, date_to, branch_ids, assigned_user_id):
        self.scope = (branch_ids, assigned_user_id)
        return SalesTotals(
            leads_total=10,
            leads_new=2,
            leads_won=4,
            leads_lost=3,
            appointments_total=8,
            appointments_completed=6,
            appointments_cancelled=1,
            appointments_no_show=1,
            paid_revenue=Decimal("500000"),
            data_as_of=datetime(2026, 7, 20, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_sales_manager_is_scoped_to_self_and_branch() -> None:
    branch_id = uuid4()
    user = make_user(UserRole.SALES_MANAGER, branch_id)
    repository = FakeSalesRepository()

    response = await SalesService(repository).overview(
        user, date(2026, 7, 1), date(2026, 7, 31), None
    )

    assert repository.scope == ([branch_id], user.id)
    assert response.lead_conversion_rate == Decimal("0.4")
    assert response.appointment_completion_rate == Decimal("0.75")


class FakeDoctorsRepository:
    async def overview(self, tenant_id, date_from, date_to, branch_ids):
        return [
            DoctorTotals(
                doctor_id=uuid4(),
                full_name="Doctor One",
                specialty="Dentist",
                appointments_total=5,
                appointments_completed=4,
                revenue_accrual=Decimal("300000"),
                revenue_payment=Decimal("250000"),
                average_rating=Decimal("4.8"),
                data_as_of=datetime(2026, 7, 20, tzinfo=UTC),
            )
        ]


@pytest.mark.asyncio
async def test_doctors_overview_calculates_completion_rate() -> None:
    response = await DoctorsService(FakeDoctorsRepository()).overview(
        make_user(UserRole.OWNER), date(2026, 7, 1), date(2026, 7, 31), None
    )

    assert response.total == 1
    assert response.items[0].completion_rate == Decimal("0.8")


class FakeMarketingRepository:
    async def overview(self, tenant_id, date_from, date_to, branch_id):
        return MarketingTotals(
            spend_by_source={"facebook": Decimal("100000"), "2gis": Decimal("50000")},
            revenue_by_source={"facebook": Decimal("400000")},
            data_as_of=datetime(2026, 7, 20, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_marketing_overview_calculates_roas() -> None:
    response = await MarketingService(FakeMarketingRepository()).overview(
        make_user(UserRole.OWNER), date(2026, 7, 1), date(2026, 7, 31), None
    )

    assert response.total_spend == Decimal("150000")
    assert response.total_attributed_revenue == Decimal("400000")
    assert response.roas == Decimal("400000") / Decimal("150000")


@pytest.mark.asyncio
async def test_marketing_rejects_administrator() -> None:
    with pytest.raises(AppError) as error:
        await MarketingService(FakeMarketingRepository()).overview(
            make_user(UserRole.ADMINISTRATOR),
            date(2026, 7, 1),
            date(2026, 7, 31),
            None,
        )

    assert error.value.code == "FORBIDDEN"
