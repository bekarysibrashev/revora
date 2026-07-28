from typing import Annotated
from fastapi import Depends
from app.core.config import Settings, get_settings
from app.modules.ai.analyst.repository import AnalystRepository
from app.modules.ai.analyst.service import AnalystService
from app.modules.ai.analyst.tools import AnalystToolRegistry
from app.modules.ai.llm_provider import OpenAIResponsesProvider
from app.modules.auth.dependencies import SessionDependency
from app.modules.dashboard.service import DashboardService
from app.modules.doctors.repository import DoctorsRepository
from app.modules.doctors.service import DoctorsService
from app.modules.finance.repository import FinanceRepository
from app.modules.finance.service import FinanceService
from app.modules.marketing.repository import MarketingRepository
from app.modules.marketing.service import MarketingService
from app.modules.sales.repository import SalesRepository
from app.modules.sales.service import SalesService

def get_analyst_service(session: SessionDependency, settings: Annotated[Settings,Depends(get_settings)]) -> AnalystService:
    finance=FinanceService(FinanceRepository(session)); sales=SalesService(SalesRepository(session))
    doctors=DoctorsService(DoctorsRepository(session)); marketing=MarketingService(MarketingRepository(session))
    dashboard=DashboardService(finance,sales,doctors,marketing)
    tools=AnalystToolRegistry(finance,sales,doctors,marketing,dashboard)
    provider=OpenAIResponsesProvider(api_key=settings.openai_api_key.get_secret_value(),model=settings.openai_model,
        base_url=settings.openai_base_url,timeout_seconds=settings.ai_request_timeout_seconds)
    return AnalystService(AnalystRepository(session),tools,provider,settings)
