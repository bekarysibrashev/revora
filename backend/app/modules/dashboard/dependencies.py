from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.dashboard.service import DashboardService
from app.modules.ai.insights.insight_repository import InsightRepository
from app.modules.ai.insights.service import InsightService
from app.modules.doctors.repository import DoctorsRepository
from app.modules.doctors.service import DoctorsService
from app.modules.finance.repository import FinanceRepository
from app.modules.finance.service import FinanceService
from app.modules.marketing.repository import MarketingRepository
from app.modules.marketing.service import MarketingService
from app.modules.sales.repository import SalesRepository
from app.modules.sales.service import SalesService

SessionDependency = Annotated[AsyncSession, Depends(get_db_session)]


def get_dashboard_service(session: SessionDependency) -> DashboardService:
    return DashboardService(
        finance=FinanceService(FinanceRepository(session)),
        sales=SalesService(SalesRepository(session)),
        doctors=DoctorsService(DoctorsRepository(session)),
        marketing=MarketingService(MarketingRepository(session)),
    )


def get_insight_service(session: SessionDependency) -> InsightService:
    return InsightService(InsightRepository(session))
