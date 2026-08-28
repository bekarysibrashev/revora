from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.modules.auth.dependencies import CurrentUser
from app.modules.contacts.dependencies import get_contact_service
from app.modules.contacts.exporter import export_new_contacts_xlsx
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
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    source: str | None = Query(default=None, pattern="^(kcell|whatsapp)$"),
) -> NewContactListResponse:
    return await service.new_contacts(
        user, date_from, date_to, page_size, page=page, source=source
    )


@router.get("/new/export")
async def export_new_contacts(
    date_from: date,
    date_to: date,
    user: CurrentUser,
    service: ContactServiceDependency,
    source: str | None = Query(default=None, pattern="^(kcell|whatsapp)$"),
) -> Response:
    rows = await service.export_rows(user, date_from, date_to, source)
    content = export_new_contacts_xlsx(rows, date_from, date_to)
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="revora-new-contacts.xlsx"'},
    )
