from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.doctors.repository import DoctorsRepository
from app.modules.doctors.service import DoctorsService

SessionDependency = Annotated[AsyncSession, Depends(get_db_session)]


def get_doctors_service(session: SessionDependency) -> DoctorsService:
    return DoctorsService(DoctorsRepository(session))
