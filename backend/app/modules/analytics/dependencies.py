from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.analytics.repository import AnalyticsRepository
from app.modules.analytics.service import AnalyticsService

SessionDependency = Annotated[AsyncSession, Depends(get_db_session)]


def get_analytics_service(session: SessionDependency) -> AnalyticsService:
    return AnalyticsService(AnalyticsRepository(session))
