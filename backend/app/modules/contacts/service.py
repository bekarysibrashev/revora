from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from app.core.errors import AppError
from app.core.security import mask_phone, phone_hash, phone_hash_candidates
from app.modules.auth.models import User, UserRole
from app.modules.contacts.models import ContactIdentity
from app.modules.contacts.repository import ContactRepository
from app.modules.contacts.schemas import NewContactItem, NewContactListResponse, NewContactSummary


class ContactRegistry:
    def __init__(self, repository: ContactRepository) -> None:
        self.repository = repository

    async def register_inbound(
        self, *, tenant_id: UUID, phone: str, source: str, occurred_at: datetime
    ) -> ContactIdentity | None:
        if source not in {"kcell", "whatsapp"}:
            raise ValueError("unsupported contact source")
        try:
            digest = phone_hash(phone)
            candidates = phone_hash_candidates(phone)
        except ValueError:
            return None
        occurred_at = occurred_at if occurred_at.tzinfo else occurred_at.replace(tzinfo=UTC)
        item = await self.repository.identity(tenant_id, digest, lock=True)
        if item is None:
            prior_at, prior_source = await self.repository.prior_inbound(tenant_id, candidates)
            first_at = min(filter(None, (prior_at, occurred_at)))
            first_source = prior_source if prior_at and prior_at <= occurred_at else source
            item = ContactIdentity(
                id=uuid4(),
                tenant_id=tenant_id,
                phone_hash=digest,
                phone_masked=mask_phone(phone),
                first_inbound_at=first_at,
                first_inbound_source=first_source,
                last_inbound_at=occurred_at,
                last_inbound_source=source,
                inbound_count=1,
                call_count=1 if source == "kcell" else 0,
                message_count=1 if source == "whatsapp" else 0,
                was_known_patient=await self.repository.is_patient(tenant_id, candidates),
            )
            inserted = await self.repository.add_if_missing(item)
            if inserted is not None:
                return inserted
            # A Kcell call and WhatsApp message can arrive simultaneously. The
            # unique key serializes them without rolling back the webhook.
            item = await self.repository.identity(tenant_id, digest, lock=True)
            if item is None:
                raise RuntimeError("contact identity conflict could not be resolved")
        item.last_inbound_at = max(item.last_inbound_at, occurred_at)
        item.last_inbound_source = source
        item.inbound_count += 1
        item.call_count += int(source == "kcell")
        item.message_count += int(source == "whatsapp")
        return item


class ContactService:
    def __init__(self, repository: ContactRepository) -> None:
        self.repository = repository

    async def new_contacts(self, user: User, date_from: date, date_to: date, limit: int = 100) -> NewContactListResponse:
        if user.role not in {UserRole.OWNER, UserRole.MANAGER}:
            raise AppError("FORBIDDEN", "New contact analytics is unavailable for this role", 403)
        if date_from > date_to:
            raise AppError("INVALID_DATE_RANGE", "date_from must not be after date_to", 422)
        total, kcell, whatsapp, existing, data_as_of = await self.repository.summary(
            user.tenant_id, date_from, date_to
        )
        rows = await self.repository.new_items(user.tenant_id, date_from, date_to, limit)
        return NewContactListResponse(
            summary=NewContactSummary(
                total=total,
                from_kcell=kcell,
                from_whatsapp=whatsapp,
                existing_patients_contacted=existing,
                date_from=date_from,
                date_to=date_to,
                data_as_of=data_as_of,
            ),
            items=[NewContactItem(
                phone_masked=item.phone_masked,
                first_contact_at=item.first_inbound_at,
                source=item.first_inbound_source,
            ) for item in rows],
        )
