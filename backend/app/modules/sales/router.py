from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import CurrentUser
from app.modules.sales.dependencies import get_sales_service
from app.modules.sales.schemas import SalesOverviewResponse
from app.modules.sales.service import SalesService

router = APIRouter(prefix="/sales", tags=["sales"])
SalesServiceDependency = Annotated[SalesService, Depends(get_sales_service)]


@router.get("/overview", response_model=SalesOverviewResponse)
async def sales_overview(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    service: SalesServiceDependency,
    branch_id: Annotated[UUID | None, Query()] = None,
) -> SalesOverviewResponse:
    return await service.overview(user, date_from, date_to, branch_id)
