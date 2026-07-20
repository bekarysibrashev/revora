"""HTTP surface of the authentication module."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.modules.auth.dependencies import CurrentUser, get_auth_service
from app.modules.auth.schemas import (
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    RefreshRequest,
    TokenResponse,
    UserResponse,
)
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])
AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, service: AuthServiceDependency) -> TokenResponse:
    return await service.login(payload.tenant_slug, payload.email, payload.password)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, service: AuthServiceDependency) -> TokenResponse:
    return await service.refresh(payload.refresh_token)


@router.post("/logout", response_model=MessageResponse)
async def logout(payload: LogoutRequest, service: AuthServiceDependency) -> MessageResponse:
    await service.logout(payload.refresh_token)
    return MessageResponse(message="Logged out")


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser) -> UserResponse:
    return AuthService._user_response(user)
