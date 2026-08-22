from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import CurrentUser
from app.modules.marketing.dependencies import get_marketing_service
from app.modules.marketing.schemas import (
    MarketingOverviewResponse,
    MetaAdsOverviewResponse,
    MetaAdsReconciliationResponse,
    MetaAdsStatusResponse,
    MetaAdsSyncResponse,
)
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


@router.get("/meta/status", response_model=MetaAdsStatusResponse)
async def meta_ads_status(
    user: CurrentUser,
    service: MarketingServiceDependency,
) -> MetaAdsStatusResponse:
    return await service.meta_status(user)


@router.get("/meta/overview", response_model=MetaAdsOverviewResponse)
async def meta_ads_overview(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    service: MarketingServiceDependency,
    account_id: Annotated[str | None, Query(max_length=50)] = None,
) -> MetaAdsOverviewResponse:
    return await service.meta_overview(user, date_from, date_to, account_id)


@router.post("/meta/sync", response_model=MetaAdsSyncResponse)
async def synchronize_meta_ads(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    service: MarketingServiceDependency,
) -> MetaAdsSyncResponse:
    return await service.sync_meta(user, date_from, date_to)


@router.get("/meta/reconcile", response_model=MetaAdsReconciliationResponse)
async def reconcile_meta_ads(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    service: MarketingServiceDependency,
) -> MetaAdsReconciliationResponse:
    return await service.reconcile_meta(user, date_from, date_to)
