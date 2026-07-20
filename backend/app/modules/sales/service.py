"""Role-aware sales analytics."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.sales.repository import SalesRepository
from app.modules.sales.schemas import SalesMeta, SalesOverviewResponse


class SalesService:
    def __init__(self, repository: SalesRepository) -> None:
        self.repository = repository

    async def overview(
        self, user: User, date_from: date, date_to: date, branch_id: UUID | None
    ) -> SalesOverviewResponse:
        if date_from > date_to:
            raise AppError("INVALID_DATE_RANGE", "date_from must not be after date_to", 422)
        branch_ids = self._branch_scope(user, branch_id)
        assigned_user_id = user.id if user.role == UserRole.SALES_MANAGER else None
        totals = await self.repository.overview(
            user.tenant_id, date_from, date_to, branch_ids, assigned_user_id
        )
        lead_rate = (
            Decimal(totals.leads_won) / Decimal(totals.leads_total)
            if totals.leads_total
            else Decimal("0")
        )
        appointment_rate = (
            Decimal(totals.appointments_completed) / Decimal(totals.appointments_total)
            if totals.appointments_total
            else Decimal("0")
        )
        return SalesOverviewResponse(
            **{
                key: value
                for key, value in totals.__dict__.items()
                if key != "data_as_of"
            },
            lead_conversion_rate=lead_rate,
            appointment_completion_rate=appointment_rate,
            meta=SalesMeta(
                date_from=date_from,
                date_to=date_to,
                branch_ids=branch_ids,
                data_as_of=totals.data_as_of,
            ),
        )

    @staticmethod
    def _branch_scope(user: User, branch_id: UUID | None) -> list[UUID] | None:
        allowed = [link.branch_id for link in user.branch_links]
        if branch_id:
            if allowed and branch_id not in allowed:
                raise AppError("BRANCH_FORBIDDEN", "Branch is outside your access scope", 403)
            return [branch_id]
        if user.role in {UserRole.ADMINISTRATOR, UserRole.SALES_MANAGER}:
            return allowed
        return None
