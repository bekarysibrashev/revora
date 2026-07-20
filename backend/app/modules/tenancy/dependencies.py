"""FastAPI dependencies for platform (cross-tenant) clinic provisioning.

Намеренно НЕ переиспользует app/modules/auth/dependencies.py (get_current_user,
require_roles): та цепочка целиком построена вокруг JWT, у которого внутри
уже есть tenant_id — но создание клиники по определению происходит ДО того,
как у неё есть хоть один тенант/пользователь/токен. Здесь — отдельный,
гораздо более узкий контур: один статический bearer-секрет
(PLATFORM_ADMIN_TOKEN), который знает только оператор платформы (вы), а не
пользователи клиник. Это НЕ роль в UserRole и никак не участвует в RLS.
"""

import secrets
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.core.errors import AppError
from app.modules.tenancy.repository import TenancyRepository
from app.modules.tenancy.service import TenancyService

platform_bearer_scheme = HTTPBearer()
SessionDependency = Annotated[AsyncSession, Depends(get_db_session)]


async def require_platform_admin(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(platform_bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    expected = settings.platform_admin_token.get_secret_value()
    if not expected or not secrets.compare_digest(credentials.credentials, expected):
        raise AppError("FORBIDDEN", "Invalid platform admin token", 403)


def get_tenancy_service(session: SessionDependency) -> TenancyService:
    return TenancyService(TenancyRepository(session))
