"""Sales and operations analytics contracts."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class SalesMeta(BaseModel):
    date_from: date
    date_to: date
    branch_ids: list[UUID] | None
    data_as_of: datetime | None


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
    appointment_completion_rate: Decimal
    paid_revenue: Decimal
    meta: SalesMeta
