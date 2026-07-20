"""Financial analytics HTTP endpoints."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.modules.auth.dependencies import CurrentUser
from app.modules.finance.dependencies import get_finance_service
from app.modules.finance.schemas import CashFlowResponse, FinanceSummaryResponse, PnlResponse
from app.modules.finance.service import FinanceService
from app.modules.reports.exporter import ReportFormat, export_cashflow, export_pnl

router = APIRouter(prefix="/finance", tags=["finance"])
FinanceServiceDependency = Annotated[FinanceService, Depends(get_finance_service)]


@router.get("/summary", response_model=FinanceSummaryResponse)
async def finance_summary(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    service: FinanceServiceDependency,
    branch_id: Annotated[UUID | None, Query()] = None,
) -> FinanceSummaryResponse:
    return await service.summary(user, date_from, date_to, branch_id)


@router.get("/pnl", response_model=PnlResponse)
async def pnl(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    service: FinanceServiceDependency,
    branch_id: Annotated[UUID | None, Query()] = None,
) -> PnlResponse:
    return await service.pnl(user, date_from, date_to, branch_id)


@router.get("/cashflow", response_model=CashFlowResponse)
async def cashflow(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    service: FinanceServiceDependency,
    branch_id: Annotated[UUID | None, Query()] = None,
) -> CashFlowResponse:
    return await service.cashflow(user, date_from, date_to, branch_id)


@router.get("/pnl/export")
async def export_pnl_report(
    date_from: date,
    date_to: date,
    format: ReportFormat,
    user: CurrentUser,
    service: FinanceServiceDependency,
    branch_id: Annotated[UUID | None, Query()] = None,
) -> Response:
    report = await service.pnl(user, date_from, date_to, branch_id)
    content = export_pnl(report, format)
    media_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if format == "xlsx"
        else "application/pdf"
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="revora-pnl.{format}"'},
    )


@router.get("/cashflow/export")
async def export_cashflow_report(
    date_from: date,
    date_to: date,
    format: ReportFormat,
    user: CurrentUser,
    service: FinanceServiceDependency,
    branch_id: Annotated[UUID | None, Query()] = None,
) -> Response:
    report = await service.cashflow(user, date_from, date_to, branch_id)
    content = export_cashflow(report, format)
    media_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if format == "xlsx"
        else "application/pdf"
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="revora-cashflow.{format}"'},
    )
