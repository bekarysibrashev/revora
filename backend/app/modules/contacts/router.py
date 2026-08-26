from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.modules.auth.dependencies import CurrentUser
from app.modules.contacts.dependencies import get_contact_service
from app.modules.contacts.schemas import NewContactListResponse
from app.modules.contacts.service import ContactService

router = APIRouter(prefix="/contacts", tags=["contacts"])
ContactServiceDependency = Annotated[ContactService, Depends(get_contact_service)]


@router.get("/new", response_model=NewContactListResponse)
async def new_contacts(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    service: ContactServiceDependency,
    limit: int = Query(default=100, ge=1, le=500),
) -> NewContactListResponse:
    return await service.new_contacts(user, date_from, date_to, limit)
