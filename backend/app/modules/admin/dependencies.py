"""FastAPI dependencies for clinic administration."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.admin.repository import AdminRepository
from app.modules.admin.service import AdminService

SessionDependency = Annotated[AsyncSession, Depends(get_db_session)]


def get_admin_service(session: SessionDependency) -> AdminService:
    return AdminService(AdminRepository(session))
