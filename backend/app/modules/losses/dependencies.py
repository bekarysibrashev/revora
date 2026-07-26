from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.losses.repository import LossRepository
from app.modules.losses.service import LossService

SessionDependency = Annotated[AsyncSession, Depends(get_db_session)]


def get_loss_service(session: SessionDependency) -> LossService:
    return LossService(LossRepository(session))
