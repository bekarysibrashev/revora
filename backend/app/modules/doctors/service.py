from datetime import date
from decimal import Decimal
from uuid import UUID

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.doctors.repository import DoctorsRepository
from app.modules.doctors.schemas import DoctorPerformance, DoctorsOverviewResponse


class DoctorsService:
    def __init__(self, repository: DoctorsRepository) -> None:
        self.repository = repository

    async def overview(
        self, user: User, date_from: date, date_to: date, branch_id: UUID | None
    ) -> DoctorsOverviewResponse:
        if user.role == UserRole.SALES_MANAGER:
            raise AppError("FORBIDDEN", "Doctors analytics are not available for this role", 403)
        if date_from > date_to:
            raise AppError("INVALID_DATE_RANGE", "date_from must not be after date_to", 422)
        branch_ids = self._branch_scope(user, branch_id)
        totals = await self.repository.overview(user.tenant_id, date_from, date_to, branch_ids)
        items = [
            DoctorPerformance(
                doctor_id=item.doctor_id,
                full_name=item.full_name,
                specialty=item.specialty,
                appointments_total=item.appointments_total,
                appointments_completed=item.appointments_completed,
                completion_rate=(
                    Decimal(item.appointments_completed) / Decimal(item.appointments_total)
                    if item.appointments_total
                    else Decimal("0")
                ),
                revenue_accrual=item.revenue_accrual,
                revenue_payment=item.revenue_payment,
                average_rating=item.average_rating,
            )
            for item in totals
        ]
        timestamps = [item.data_as_of for item in totals if item.data_as_of]
        return DoctorsOverviewResponse(
            items=items,
            total=len(items),
            date_from=date_from,
            date_to=date_to,
            branch_ids=branch_ids,
            data_as_of=max(timestamps) if timestamps else None,
        )

    @staticmethod
    def _branch_scope(user: User, branch_id: UUID | None) -> list[UUID] | None:
        allowed = [link.branch_id for link in user.branch_links]
        if branch_id:
            if allowed and branch_id not in allowed:
                raise AppError("BRANCH_FORBIDDEN", "Branch is outside your access scope", 403)
            return [branch_id]
        return allowed if user.role == UserRole.ADMINISTRATOR else None
