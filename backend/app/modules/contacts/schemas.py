from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class NewContactItem(BaseModel):
    id: UUID
    phone_number: str | None
    first_contact_at: datetime
    source: str
    last_contact_at: datetime
    inbound_count: int
    call_count: int
    message_count: int


class NewContactSummary(BaseModel):
    total: int
    from_kcell: int
    from_whatsapp: int
    existing_patients_contacted: int
    date_from: date
    date_to: date
    data_as_of: datetime | None


class NewContactListResponse(BaseModel):
    summary: NewContactSummary
    items: list[NewContactItem]
    page: int
    page_size: int
    total_pages: int
