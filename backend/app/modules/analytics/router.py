from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.analytics.dependencies import get_analytics_service
from app.modules.analytics.schemas import DataQualityResponse, MetricCatalogResponse
from app.modules.analytics.service import AnalyticsService
from app.modules.auth.dependencies import CurrentUser

router = APIRouter(prefix="/analytics", tags=["analytics"])
AnalyticsServiceDependency = Annotated[AnalyticsService, Depends(get_analytics_service)]


@router.get("/quality", response_model=DataQualityResponse)
async def data_quality(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    service: AnalyticsServiceDependency,
    branch_id: Annotated[UUID | None, Query()] = None,
) -> DataQualityResponse:
    return await service.quality(user, date_from, date_to, branch_id)


@router.get("/metrics", response_model=MetricCatalogResponse)
async def metric_catalog(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    service: AnalyticsServiceDependency,
    branch_id: Annotated[UUID | None, Query()] = None,
) -> MetricCatalogResponse:
    return await service.metric_catalog(user, date_from, date_to, branch_id)
