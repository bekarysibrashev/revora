from datetime import date
from uuid import UUID

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.dashboard.schemas import DashboardCeoResponse
from app.modules.doctors.service import DoctorsService
from app.modules.finance.service import FinanceService
from app.modules.marketing.service import MarketingService
from app.modules.sales.service import SalesService


class DashboardService:
    def __init__(
        self,
        finance: FinanceService,
        sales: SalesService,
        doctors: DoctorsService,
        marketing: MarketingService,
    ) -> None:
        self.finance = finance
        self.sales = sales
        self.doctors = doctors
        self.marketing = marketing

    async def ceo(
        self, user: User, date_from: date, date_to: date, branch_id: UUID | None
    ) -> DashboardCeoResponse:
        if user.role not in {UserRole.OWNER, UserRole.MANAGER}:
            raise AppError("FORBIDDEN", "CEO dashboard is not available for this role", 403)
        finance = await self.finance.summary(user, date_from, date_to, branch_id)
        sales = await self.sales.overview(user, date_from, date_to, branch_id)
        doctors = await self.doctors.overview(user, date_from, date_to, branch_id)
        marketing = await self.marketing.overview(user, date_from, date_to, branch_id)
        timestamps = [
            item
            for item in (
                finance.meta.data_as_of,
                sales.meta.data_as_of,
                doctors.data_as_of,
                marketing.data_as_of,
            )
            if item
        ]
        return DashboardCeoResponse(
            finance=finance,
            sales=sales,
            top_doctors=doctors.items[:5],
            marketing=marketing,
            date_from=date_from,
            date_to=date_to,
            branch_id=branch_id,
            data_as_of=max(timestamps) if timestamps else None,
        )
