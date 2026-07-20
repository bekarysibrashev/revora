"""FastAPI wiring for financial analytics."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.finance.repository import FinanceRepository
from app.modules.finance.service import FinanceService

SessionDependency = Annotated[AsyncSession, Depends(get_db_session)]


def get_finance_service(session: SessionDependency) -> FinanceService:
    return FinanceService(FinanceRepository(session))
