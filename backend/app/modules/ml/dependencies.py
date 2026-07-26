from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.ml.repository import MLRepository
from app.modules.ml.service import MLService

SessionDependency = Annotated[AsyncSession, Depends(get_db_session)]


def get_ml_service(session: SessionDependency) -> MLService:
    return MLService(MLRepository(session))
