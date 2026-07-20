"""FastAPI authentication and authorization dependencies."""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.core.errors import AppError
from app.core.security import InvalidAccessToken, decode_access_token
from app.modules.auth.models import User, UserRole
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService

bearer_scheme = HTTPBearer()
SessionDependency = Annotated[AsyncSession, Depends(get_db_session)]


def get_auth_service(
    session: SessionDependency, settings: Annotated[Settings, Depends(get_settings)]
) -> AuthService:
    return AuthService(AuthRepository(session), settings)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    session: SessionDependency,
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    try:
        payload = decode_access_token(credentials.credentials, settings)
    except InvalidAccessToken as exc:
        raise AppError("INVALID_ACCESS_TOKEN", str(exc), 401) from exc

    repository = AuthRepository(session)
    tenant_id = UUID(payload["tenant_id"])
    await repository.set_tenant_context(tenant_id)
    user = await repository.get_user_by_id(UUID(payload["sub"]))
    if user is None or not user.is_active or user.tenant_id != tenant_id or user.role.value != payload.get("role"):
        raise AppError("INVALID_ACCESS_TOKEN", "User is unavailable or token is stale", 401)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*allowed_roles: UserRole) -> Callable[[CurrentUser], User]:
    async def role_dependency(user: CurrentUser) -> User:
        if user.role not in allowed_roles:
            raise AppError("FORBIDDEN", "You do not have permission for this action", 403)
        return user

    return role_dependency
