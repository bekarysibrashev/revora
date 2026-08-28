"""FastAPI dependencies for Telegram administration."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.telegram.repository import TelegramRepository
from app.modules.telegram.service import TelegramService

SessionDependency = Annotated[AsyncSession, Depends(get_db_session)]


def get_telegram_service(session: SessionDependency) -> TelegramService:
    return TelegramService(TelegramRepository(session))

