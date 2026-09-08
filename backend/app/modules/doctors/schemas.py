from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.modules.reports.schemas import (
    CoverageInfoResponse,
    DimensionReconciliationResponse,
)


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
    coverage: CoverageInfoResponse | None = None
    # Empty only when no official totals exist for the period at all.
    # A "partial" entry here means the doctor column does not add up to
    # the clinic total and the residual is unexplained -- the reader is
    # told rather than shown a reconciled-looking table.
    reconciliation: list[DimensionReconciliationResponse] = []
