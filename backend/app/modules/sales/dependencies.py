from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.sales.repository import SalesRepository
from app.modules.sales.service import SalesService

SessionDependency = Annotated[AsyncSession, Depends(get_db_session)]


def get_sales_service(session: SessionDependency) -> SalesService:
    return SalesService(SalesRepository(session))
