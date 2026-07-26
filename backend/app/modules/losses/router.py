from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import CurrentUser
from app.modules.losses.dependencies import get_loss_service
from app.modules.losses.schemas import (
    LossMapResponse,
    LossOpportunityResponse,
    LossRefreshResponse,
    LossUpdateRequest,
)
from app.modules.losses.service import LossService

router = APIRouter(prefix="/losses", tags=["losses"])
LossServiceDependency = Annotated[LossService, Depends(get_loss_service)]


@router.get("/map", response_model=LossMapResponse)
async def loss_map(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    service: LossServiceDependency,
    branch_id: Annotated[UUID | None, Query()] = None,
) -> LossMapResponse:
    return await service.map(user, date_from, date_to, branch_id)


@router.post("/refresh", response_model=LossRefreshResponse)
async def refresh_loss_map(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    service: LossServiceDependency,
    branch_id: Annotated[UUID | None, Query()] = None,
) -> LossRefreshResponse:
    return await service.refresh(user, date_from, date_to, branch_id)


@router.patch("/{opportunity_id}", response_model=LossOpportunityResponse)
async def update_loss(
    opportunity_id: UUID,
    payload: LossUpdateRequest,
    user: CurrentUser,
    service: LossServiceDependency,
) -> LossOpportunityResponse:
    return await service.update(user, opportunity_id, payload)
