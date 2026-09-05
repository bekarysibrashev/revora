"""Sales and operations analytics contracts."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.reports.schemas import CoverageInfoResponse


class SalesMeta(BaseModel):
    date_from: date
    date_to: date
    branch_ids: list[UUID] | None
    data_as_of: datetime | None
    coverage: dict[str, CoverageInfoResponse] = Field(default_factory=dict)


class SalesOverviewResponse(BaseModel):
    leads_total: int
    leads_new: int
    leads_won: int
    leads_lost: int
    lead_conversion_rate: Decimal
    appointments_total: int
    appointments_completed: int
    appointments_cancelled: int
    appointments_no_show: int
    patients_total: int
    patients_primary: int
    patients_repeat: int
    appointment_completion_rate: Decimal
    paid_revenue: Decimal
    appointments_transferred: int = 0
    treatment_plan_created: int = 0
    treatment_plan_accepted: int = 0
    treatment_plan_paid: Decimal | None = None
    patients_inactive: int = 0
    inquiry_to_treatment_rate: Decimal | None = None
    consultation_to_plan_rate: Decimal | None = None
    plan_to_payment_rate: Decimal | None = None
    meta: SalesMeta
