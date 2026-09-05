from datetime import date
from decimal import Decimal
from uuid import UUID

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.contacts.service import ContactService
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
        contacts: ContactService,
    ) -> None:
        self.finance = finance
        self.sales = sales
        self.doctors = doctors
        self.marketing = marketing
        self.contacts = contacts

    async def ceo(
        self, user: User, date_from: date, date_to: date, branch_id: UUID | None
    ) -> DashboardCeoResponse:
        if user.role not in {UserRole.OWNER, UserRole.MANAGER}:
            raise AppError("FORBIDDEN", "CEO dashboard is not available for this role", 403)
        finance = await self.finance.summary(user, date_from, date_to, branch_id)
        sales = await self.sales.overview(user, date_from, date_to, branch_id)
        doctors = await self.doctors.overview(user, date_from, date_to, branch_id)
        marketing = await self.marketing.overview(user, date_from, date_to, branch_id)
        new_contacts = (await self.contacts.new_contacts(user, date_from, date_to, limit=1)).summary
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
        # Task 2: CAC ("Стоимость первичного пациента" is the same figure
        # under its other common label in dental-clinic reporting, not a
        # second formula) -- needs marketing spend and a 1C-confirmed
        # primary-patient count together, so it is computed here rather
        # than inside either module alone. None (never a fabricated 0)
        # when there were no confirmed primary patients to divide by.
        cac = (
            marketing.total_spend / Decimal(sales.patients_primary)
            if sales.patients_primary
            else None
        )
        return DashboardCeoResponse(
            finance=finance,
            sales=sales,
            top_doctors=doctors.items[:5],
            marketing=marketing,
            new_contacts=new_contacts,
            cac=cac,
            cost_of_first_patient=cac,
            date_from=date_from,
            date_to=date_to,
            branch_id=branch_id,
            data_as_of=max(timestamps) if timestamps else None,
        )
