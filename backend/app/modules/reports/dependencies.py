from typing import Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.reports.repository import OfficialReportsRepository
from app.modules.reports.service import OfficialReportsService

SessionDependency = Annotated[AsyncSession, Depends(get_db_session)]


def get_official_reports_service(session: SessionDependency) -> OfficialReportsService:
    return OfficialReportsService(OfficialReportsRepository(session))
