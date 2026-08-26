from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.modules.auth.dependencies import CurrentUser
from app.modules.reports.dependencies import get_official_reports_service
from app.modules.reports.schemas import OfficialReportListResponse, OfficialReportResponse
from app.modules.reports.service import OfficialReportsService

router = APIRouter(prefix="/reports/official-1c", tags=["official-1c-reports"])
ServiceDependency = Annotated[OfficialReportsService, Depends(get_official_reports_service)]


@router.get("", response_model=OfficialReportListResponse)
async def list_official_reports(user: CurrentUser, service: ServiceDependency) -> OfficialReportListResponse:
    return await service.list_active(user)


@router.post("", response_model=OfficialReportResponse, status_code=status.HTTP_201_CREATED)
async def upload_official_report(
    request: Request, user: CurrentUser, service: ServiceDependency,
    filename: Annotated[str, Query(min_length=1, max_length=500)],
    period_from: date, period_to: date,
) -> OfficialReportResponse:
    return await service.upload(
        user, content=await request.body(), filename=filename,
        period_from=period_from, period_to=period_to,
    )
