from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import CurrentUser
from app.modules.ai.insights.service import InsightService
from app.modules.dashboard.dependencies import get_dashboard_service, get_insight_service
from app.modules.dashboard.schemas import (
    DashboardCeoResponse,
    InsightDismissResponse,
    InsightListResponse,
)
from app.modules.dashboard.service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
DashboardServiceDependency = Annotated[DashboardService, Depends(get_dashboard_service)]
InsightServiceDependency = Annotated[InsightService, Depends(get_insight_service)]


@router.get("/ceo", response_model=DashboardCeoResponse)
async def dashboard_ceo(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    service: DashboardServiceDependency,
    branch_id: Annotated[UUID | None, Query()] = None,
) -> DashboardCeoResponse:
    return await service.ceo(user, date_from, date_to, branch_id)


@router.get("/insights", response_model=InsightListResponse)
async def list_insights(
    user: CurrentUser,
    service: InsightServiceDependency,
    branch_id: Annotated[UUID | None, Query()] = None,
    severity: Annotated[str | None, Query(max_length=20)] = None,
    insight_type: Annotated[str | None, Query(max_length=50)] = None,
) -> InsightListResponse:
    return await service.list_insights(
        user, branch_id=branch_id, severity=severity, insight_type=insight_type
    )


@router.post("/insights/{insight_id}/dismiss", response_model=InsightDismissResponse)
async def dismiss_insight(
    insight_id: UUID,
    user: CurrentUser,
    service: InsightServiceDependency,
) -> InsightDismissResponse:
    await service.dismiss(user, insight_id)
    return InsightDismissResponse()
