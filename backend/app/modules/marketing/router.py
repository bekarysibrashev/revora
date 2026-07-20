from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import CurrentUser
from app.modules.marketing.dependencies import get_marketing_service
from app.modules.marketing.schemas import MarketingOverviewResponse
from app.modules.marketing.service import MarketingService

router = APIRouter(prefix="/marketing", tags=["marketing"])
MarketingServiceDependency = Annotated[MarketingService, Depends(get_marketing_service)]


@router.get("/overview", response_model=MarketingOverviewResponse)
async def marketing_overview(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    service: MarketingServiceDependency,
    branch_id: Annotated[UUID | None, Query()] = None,
) -> MarketingOverviewResponse:
    return await service.overview(user, date_from, date_to, branch_id)
