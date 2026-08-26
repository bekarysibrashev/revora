from datetime import date, datetime

from pydantic import BaseModel


class NewContactItem(BaseModel):
    phone_masked: str | None
    first_contact_at: datetime
    source: str


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
