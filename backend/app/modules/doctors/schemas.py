from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class DoctorPerformance(BaseModel):
    doctor_id: UUID
    full_name: str
    specialty: str | None
    appointments_total: int
    appointments_completed: int
    completion_rate: Decimal
    revenue_accrual: Decimal
    revenue_payment: Decimal
    average_rating: Decimal | None


class DoctorsOverviewResponse(BaseModel):
    items: list[DoctorPerformance]
    total: int
    date_from: date
    date_to: date
    branch_ids: list[UUID] | None
    data_as_of: datetime | None
