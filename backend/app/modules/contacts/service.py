from datetime import UTC, date, datetime
from math import ceil
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import mask_phone, normalize_phone_e164, phone_hash, phone_hash_candidates
from app.modules.auth.models import User, UserRole
from app.modules.contacts.models import ContactIdentity
from app.modules.contacts.repository import ContactRepository
from app.modules.contacts.schemas import NewContactItem, NewContactListResponse, NewContactSummary
from app.modules.whatsapp.security import WhatsAppDataProtectionError, decrypt_contact, encrypt_contact


class ContactRegistry:
    def __init__(self, repository: ContactRepository, data_secret: str = "") -> None:
        self.repository = repository
        self.data_secret = data_secret

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
                phone_ciphertext=self._encrypt_phone(phone),
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
        if not item.phone_ciphertext:
            item.phone_ciphertext = self._encrypt_phone(phone)
        if not item.was_known_patient:
            item.was_known_patient = await self.repository.is_patient(tenant_id, candidates)
        item.inbound_count += 1
        item.call_count += int(source == "kcell")
        item.message_count += int(source == "whatsapp")
        return item

    def _encrypt_phone(self, phone: str) -> str | None:
        if not self.data_secret:
            return None
        try:
            return encrypt_contact(normalize_phone_e164(phone), self.data_secret)
        except (ValueError, WhatsAppDataProtectionError):
            return None


class ContactService:
    def __init__(self, repository: ContactRepository, settings: Settings | None = None) -> None:
        self.repository = repository
        self.settings = settings

    async def new_contacts(
        self,
        user: User,
        date_from: date,
        date_to: date,
        limit: int = 100,
        *,
        page: int = 1,
        source: str | None = None,
    ) -> NewContactListResponse:
        if user.role not in {UserRole.OWNER, UserRole.MANAGER, UserRole.ADMINISTRATOR}:
            raise AppError("FORBIDDEN", "New contact analytics is unavailable for this role", 403)
        if date_from > date_to:
            raise AppError("INVALID_DATE_RANGE", "date_from must not be after date_to", 422)
        await self._materialize_history(user.tenant_id, date_from, date_to)
        total, kcell, whatsapp, existing, data_as_of = await self.repository.summary(
            user.tenant_id, date_from, date_to
        )
        filtered_total = await self.repository.count_new_items(
            user.tenant_id, date_from, date_to, source
        )
        rows = await self.repository.new_items(
            user.tenant_id,
            date_from,
            date_to,
            limit,
            offset=(page - 1) * limit,
            source=source,
        )
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
                id=item.id,
                phone_number=self._decrypt_phone(item),
                first_contact_at=item.first_inbound_at,
                source=item.first_inbound_source,
                last_contact_at=item.last_inbound_at,
                inbound_count=item.inbound_count,
                call_count=item.call_count,
                message_count=item.message_count,
            ) for item in rows],
            page=page,
            page_size=limit,
            total_pages=max(1, ceil(filtered_total / limit)),
        )

    async def export_rows(
        self, user: User, date_from: date, date_to: date, source: str | None = None
    ) -> list[NewContactItem]:
        if user.role not in {UserRole.OWNER, UserRole.MANAGER, UserRole.ADMINISTRATOR}:
            raise AppError("FORBIDDEN", "New contact export is unavailable for this role", 403)
        if date_from > date_to:
            raise AppError("INVALID_DATE_RANGE", "date_from must not be after date_to", 422)
        await self._materialize_history(user.tenant_id, date_from, date_to)
        rows = await self.repository.new_items(
            user.tenant_id, date_from, date_to, 50_000, source=source
        )
        return [NewContactItem(
            id=item.id,
            phone_number=self._decrypt_phone(item),
            first_contact_at=item.first_inbound_at,
            source=item.first_inbound_source,
            last_contact_at=item.last_inbound_at,
            inbound_count=item.inbound_count,
            call_count=item.call_count,
            message_count=item.message_count,
        ) for item in rows]

    def _decrypt_phone(self, item: ContactIdentity) -> str | None:
        secret = self.settings.whatsapp_data_key.get_secret_value() if self.settings else ""
        if not secret or not item.phone_ciphertext:
            return None
        try:
            return decrypt_contact(item.phone_ciphertext, secret)
        except WhatsAppDataProtectionError:
            return None

    async def _materialize_history(
        self, tenant_id: UUID, date_from: date, date_to: date
    ) -> None:
        secret = self.settings.whatsapp_data_key.get_secret_value() if self.settings else ""
        if not secret:
            raise AppError(
                "CONTACT_DATA_KEY_MISSING",
                "WHATSAPP_DATA_KEY is required to show full contact phone numbers",
                503,
            )
        events: list[tuple[str, str, datetime]] = []
        for payload, occurred_at in await self.repository.historical_kcell_inbounds(
            tenant_id, date_from, date_to
        ):
            phone = str(payload.get("phone") or "").strip()
            if phone:
                events.append((phone, "kcell", occurred_at))
        for ciphertext, occurred_at in await self.repository.historical_whatsapp_inbounds(
            tenant_id, date_from, date_to
        ):
            try:
                events.append((decrypt_contact(ciphertext, secret), "whatsapp", occurred_at))
            except WhatsAppDataProtectionError:
                continue

        grouped: dict[str, dict[str, object]] = {}
        for phone, source, occurred_at in events:
            try:
                normalized = normalize_phone_e164(phone)
                digest = phone_hash(normalized)
            except ValueError:
                continue
            current = grouped.setdefault(digest, {
                "phone": normalized,
                "first_at": occurred_at,
                "first_source": source,
                "last_at": occurred_at,
                "calls": 0,
                "messages": 0,
            })
            if occurred_at < current["first_at"]:
                current["first_at"] = occurred_at
                current["first_source"] = source
            current["last_at"] = max(current["last_at"], occurred_at)
            current["calls"] += int(source == "kcell")
            current["messages"] += int(source == "whatsapp")

        for digest, data in grouped.items():
            item = await self.repository.identity(tenant_id, digest, lock=True)
            phone = str(data["phone"])
            if item is None:
                candidates = phone_hash_candidates(phone)
                prior_at, prior_source = await self.repository.prior_inbound(tenant_id, candidates)
                first_at = min(filter(None, (prior_at, data["first_at"])))
                first_source = prior_source if prior_at and prior_at <= data["first_at"] else str(data["first_source"])
                item = ContactIdentity(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    phone_hash=digest,
                    phone_masked=None,
                    phone_ciphertext=encrypt_contact(phone, secret),
                    first_inbound_at=first_at,
                    first_inbound_source=first_source,
                    last_inbound_at=data["last_at"],
                    last_inbound_source=str(data["first_source"]),
                    inbound_count=int(data["calls"]) + int(data["messages"]),
                    call_count=int(data["calls"]),
                    message_count=int(data["messages"]),
                    was_known_patient=await self.repository.is_patient(tenant_id, candidates),
                )
                await self.repository.add_if_missing(item)
                continue
            if not item.phone_ciphertext:
                item.phone_ciphertext = encrypt_contact(phone, secret)
            item.first_inbound_at = min(item.first_inbound_at, data["first_at"])
            item.last_inbound_at = max(item.last_inbound_at, data["last_at"])
            item.call_count = max(item.call_count, int(data["calls"]))
            item.message_count = max(item.message_count, int(data["messages"]))
            item.inbound_count = max(item.inbound_count, item.call_count + item.message_count)
