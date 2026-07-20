"""HTTP endpoints for clinic administration."""

from typing import Annotated

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.modules.admin.dependencies import get_admin_service
from app.modules.admin.schemas import (
    AdminUserCreateRequest,
    AdminUserListResponse,
    AdminUserResponse,
    AdminUserUpdateRequest,
    BranchCreateRequest,
    BranchListResponse,
    BranchResponse,
    BranchUpdateRequest,
)
from app.modules.admin.service import AdminService
from app.modules.auth.dependencies import CurrentUser

router = APIRouter(prefix="/admin", tags=["admin"])
AdminServiceDependency = Annotated[AdminService, Depends(get_admin_service)]


@router.get("/branches", response_model=BranchListResponse)
async def list_branches(
    user: CurrentUser, service: AdminServiceDependency
) -> BranchListResponse:
    return await service.list_branches(user)


@router.post("/branches", response_model=BranchResponse, status_code=status.HTTP_201_CREATED)
async def create_branch(
    payload: BranchCreateRequest,
    user: CurrentUser,
    service: AdminServiceDependency,
) -> BranchResponse:
    return await service.create_branch(user, payload)


@router.patch("/branches/{branch_id}", response_model=BranchResponse)
async def update_branch(
    branch_id: UUID,
    payload: BranchUpdateRequest,
    user: CurrentUser,
    service: AdminServiceDependency,
) -> BranchResponse:
    return await service.update_branch(user, branch_id, payload)


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    user: CurrentUser, service: AdminServiceDependency
) -> AdminUserListResponse:
    return await service.list_users(user)


@router.post("/users", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: AdminUserCreateRequest,
    user: CurrentUser,
    service: AdminServiceDependency,
) -> AdminUserResponse:
    return await service.create_user(user, payload)


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: UUID,
    payload: AdminUserUpdateRequest,
    user: CurrentUser,
    service: AdminServiceDependency,
) -> AdminUserResponse:
    return await service.update_user(user, user_id, payload)
