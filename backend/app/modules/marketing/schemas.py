from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class MarketingSourcePerformance(BaseModel):
    source: str
    spend: Decimal
    attributed_revenue: Decimal
    roas: Decimal | None


class MarketingOverviewResponse(BaseModel):
    total_spend: Decimal
    total_attributed_revenue: Decimal
    roas: Decimal | None
    sources: list[MarketingSourcePerformance]
    date_from: date
    date_to: date
    branch_id: UUID | None
    data_as_of: datetime | None
