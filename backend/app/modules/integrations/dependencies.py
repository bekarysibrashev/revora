"""FastAPI dependency wiring for integrations."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.integrations.canonical_writer import CanonicalWriter
from app.modules.integrations.repository import IntegrationRepository
from app.modules.integrations.service import IntegrationService

SessionDependency = Annotated[AsyncSession, Depends(get_db_session)]


def get_integration_service(session: SessionDependency) -> IntegrationService:
    return IntegrationService(IntegrationRepository(session), CanonicalWriter(session))
