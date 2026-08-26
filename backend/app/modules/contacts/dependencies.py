from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.contacts.repository import ContactRepository
from app.modules.contacts.service import ContactService

SessionDependency = Annotated[AsyncSession, Depends(get_db_session)]


def get_contact_service(session: SessionDependency) -> ContactService:
    return ContactService(ContactRepository(session))
