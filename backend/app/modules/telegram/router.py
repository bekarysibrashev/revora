"""Owner/manager API for Telegram enrollment, tasks and reports."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.modules.auth.dependencies import CurrentUser
from app.modules.telegram.dependencies import get_telegram_service
from app.modules.telegram.schemas import (
    EmployeeListResponse,
    EmployeeResponse,
    EmployeeUpdateRequest,
    InvitationCreateRequest,
    InvitationResponse,
    ReportSubscriptionRequest,
    TaskCreateRequest,
    TaskListResponse,
    TaskResponse,
)
from app.modules.telegram.service import TelegramService

router = APIRouter(prefix="/telegram", tags=["telegram"])
ServiceDependency = Annotated[TelegramService, Depends(get_telegram_service)]


@router.post("/invitations", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    payload: InvitationCreateRequest, user: CurrentUser, service: ServiceDependency
) -> InvitationResponse:
    return await service.create_invitation(user, payload)


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: UUID, user: CurrentUser, service: ServiceDependency
) -> Response:
    await service.revoke_invitation(user, invitation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/employees", response_model=EmployeeListResponse)
async def list_employees(user: CurrentUser, service: ServiceDependency) -> EmployeeListResponse:
    return await service.list_employees(user)


@router.patch("/employees/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: UUID,
    payload: EmployeeUpdateRequest,
    user: CurrentUser,
    service: ServiceDependency,
) -> EmployeeResponse:
    return await service.update_employee(user, employee_id, payload)


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreateRequest, user: CurrentUser, service: ServiceDependency
) -> TaskResponse:
    return await service.create_task(user, payload)


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(user: CurrentUser, service: ServiceDependency) -> TaskListResponse:
    return await service.list_tasks(user)


@router.post("/tasks/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(
    task_id: UUID, user: CurrentUser, service: ServiceDependency
) -> TaskResponse:
    return await service.cancel_task(user, task_id)


@router.put("/employees/{employee_id}/reports", status_code=status.HTTP_204_NO_CONTENT)
async def configure_report(
    employee_id: UUID,
    payload: ReportSubscriptionRequest,
    user: CurrentUser,
    service: ServiceDependency,
) -> Response:
    await service.configure_report(user, employee_id, payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

