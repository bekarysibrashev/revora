from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import CurrentUser
from app.modules.ml.dependencies import get_ml_service
from app.modules.ml.schemas import (
    DatasetSnapshotListResponse,
    DatasetSnapshotResponse,
    MLRegistryResponse,
    NoShowReadinessResponse,
)
from app.modules.ml.service import MLService

router = APIRouter(prefix="/ml", tags=["ml"])
MLServiceDependency = Annotated[MLService, Depends(get_ml_service)]


@router.get("/no-show/readiness", response_model=NoShowReadinessResponse)
async def no_show_readiness(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    service: MLServiceDependency,
    branch_id: Annotated[UUID | None, Query()] = None,
) -> NoShowReadinessResponse:
    return await service.no_show_readiness(user, date_from, date_to, branch_id)


@router.post("/no-show/snapshots", response_model=DatasetSnapshotResponse)
async def create_no_show_snapshot(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    service: MLServiceDependency,
    branch_id: Annotated[UUID | None, Query()] = None,
) -> DatasetSnapshotResponse:
    return await service.create_snapshot(user, date_from, date_to, branch_id)


@router.get("/snapshots", response_model=DatasetSnapshotListResponse)
async def list_snapshots(
    user: CurrentUser, service: MLServiceDependency
) -> DatasetSnapshotListResponse:
    return await service.snapshots(user)


@router.get("/registry", response_model=MLRegistryResponse)
async def registry(
    user: CurrentUser, service: MLServiceDependency
) -> MLRegistryResponse:
    return await service.registry(user)
