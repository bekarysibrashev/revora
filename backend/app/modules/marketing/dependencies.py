from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.marketing.repository import MarketingRepository
from app.modules.marketing.service import MarketingService

SessionDependency = Annotated[AsyncSession, Depends(get_db_session)]


def get_marketing_service(session: SessionDependency) -> MarketingService:
    return MarketingService(MarketingRepository(session))
