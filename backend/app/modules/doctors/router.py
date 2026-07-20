from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import CurrentUser
from app.modules.doctors.dependencies import get_doctors_service
from app.modules.doctors.schemas import DoctorsOverviewResponse
from app.modules.doctors.service import DoctorsService

router = APIRouter(prefix="/doctors", tags=["doctors"])
DoctorsServiceDependency = Annotated[DoctorsService, Depends(get_doctors_service)]


@router.get("/overview", response_model=DoctorsOverviewResponse)
async def doctors_overview(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    service: DoctorsServiceDependency,
    branch_id: Annotated[UUID | None, Query()] = None,
) -> DoctorsOverviewResponse:
    return await service.overview(user, date_from, date_to, branch_id)
