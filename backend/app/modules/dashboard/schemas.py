from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel

from app.modules.doctors.schemas import DoctorPerformance
from app.modules.finance.schemas import FinanceSummaryResponse
from app.modules.marketing.schemas import MarketingOverviewResponse
from app.modules.sales.schemas import SalesOverviewResponse


class DashboardCeoResponse(BaseModel):
    finance: FinanceSummaryResponse
    sales: SalesOverviewResponse
    top_doctors: list[DoctorPerformance]
    marketing: MarketingOverviewResponse
    date_from: date
    date_to: date
    branch_id: UUID | None
    data_as_of: datetime | None


class InsightResponse(BaseModel):
    id: UUID
    branch_id: UUID | None
    insight_type: str
    severity: str
    title: str
    description: str
    evidence: dict[str, object]
    detected_at: datetime
    valid_until: datetime | None


class InsightListResponse(BaseModel):
    items: list[InsightResponse]
    total: int


class InsightDismissResponse(BaseModel):
    message: str = "Insight dismissed"
