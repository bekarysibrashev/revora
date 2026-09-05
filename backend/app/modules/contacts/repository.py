from datetime import date, datetime
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts.models import ContactIdentity
from app.modules.kcell.models import KcellWebhookReceipt
from app.modules.sales.models import Call, Patient
from app.modules.whatsapp.models import WhatsAppConversation, WhatsAppMessage
from app.shared.timezone import clinic_day_end_exclusive, clinic_day_start


class ContactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def identity(self, tenant_id: UUID, digest: str, *, lock: bool = False) -> ContactIdentity | None:
        statement = select(ContactIdentity).where(
            ContactIdentity.tenant_id == tenant_id,
            ContactIdentity.phone_hash == digest,
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def is_patient(self, tenant_id: UUID, candidates: set[str]) -> bool:
        # A deleted/inactive 1C patient record must not block a genuine
        # new_contact classification -- if 1C no longer considers them an
        # active patient, Revora shouldn't either.
        return bool(await self.session.scalar(
            select(Patient.id).where(
                Patient.tenant_id == tenant_id,
                Patient.phone_hash.in_(candidates),
                Patient.is_active.is_(True),
            ).limit(1)
        ))

    async def prior_inbound(self, tenant_id: UUID, candidates: set[str]) -> tuple[datetime | None, str | None]:
        first_call = await self.session.scalar(
            select(func.min(Call.started_at)).where(
                Call.tenant_id == tenant_id,
                Call.phone_hash.in_(candidates),
                func.lower(Call.direction).in_(("in", "incoming", "inbound", "входящий")),
            )
        )
        first_message = await self.session.scalar(
            select(func.min(func.coalesce(WhatsAppMessage.provider_timestamp, WhatsAppMessage.created_at)))
            .join(WhatsAppConversation, WhatsAppConversation.id == WhatsAppMessage.conversation_id)
            .where(
                WhatsAppMessage.tenant_id == tenant_id,
                WhatsAppMessage.direction == "in",
                WhatsAppConversation.contact_hash.in_(candidates),
            )
        )
        if first_call is None:
            return first_message, "whatsapp" if first_message else None
        if first_message is None or first_call <= first_message:
            return first_call, "kcell"
        return first_message, "whatsapp"

    async def add_if_missing(self, item: ContactIdentity) -> ContactIdentity | None:
        statement = insert(ContactIdentity).values(
            id=item.id,
            tenant_id=item.tenant_id,
            phone_hash=item.phone_hash,
            phone_masked=item.phone_masked,
            phone_ciphertext=item.phone_ciphertext,
            first_inbound_at=item.first_inbound_at,
            first_inbound_source=item.first_inbound_source,
            last_inbound_at=item.last_inbound_at,
            last_inbound_source=item.last_inbound_source,
            inbound_count=item.inbound_count,
            call_count=item.call_count,
            message_count=item.message_count,
            was_known_patient=item.was_known_patient,
        ).on_conflict_do_nothing(
            index_elements=["tenant_id", "phone_hash"]
        ).returning(ContactIdentity)
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def historical_kcell_inbounds(
        self, tenant_id: UUID, date_from: date, date_to: date
    ) -> list[tuple[dict, datetime]]:
        start = clinic_day_start(date_from)
        end = clinic_day_end_exclusive(date_to)
        rows = await self.session.execute(
            select(KcellWebhookReceipt.payload, Call.started_at)
            .join(
                Call,
                (Call.tenant_id == KcellWebhookReceipt.tenant_id)
                & (Call.external_id == KcellWebhookReceipt.call_id),
            )
            .where(
                Call.tenant_id == tenant_id,
                Call.started_at >= start,
                Call.started_at < end,
                func.lower(Call.direction).in_(("in", "incoming", "inbound", "входящий")),
                KcellWebhookReceipt.command == "history",
            )
        )
        return [(payload or {}, occurred_at) for payload, occurred_at in rows.all()]

    async def historical_whatsapp_inbounds(
        self, tenant_id: UUID, date_from: date, date_to: date
    ) -> list[tuple[str, datetime]]:
        start = clinic_day_start(date_from)
        end = clinic_day_end_exclusive(date_to)
        occurred_at = func.coalesce(WhatsAppMessage.provider_timestamp, WhatsAppMessage.created_at)
        rows = await self.session.execute(
            select(WhatsAppConversation.contact_ciphertext, occurred_at)
            .join(WhatsAppMessage, WhatsAppMessage.conversation_id == WhatsAppConversation.id)
            .where(
                WhatsAppMessage.tenant_id == tenant_id,
                WhatsAppMessage.direction == "in",
                occurred_at >= start,
                occurred_at < end,
            )
        )
        return list(rows.all())

    async def summary(self, tenant_id: UUID, date_from: date, date_to: date) -> tuple[int, int, int, int, datetime | None]:
        start = clinic_day_start(date_from)
        end = clinic_day_end_exclusive(date_to)
        patient_exists = exists(
            select(Patient.id).where(
                Patient.tenant_id == tenant_id,
                Patient.phone_hash == ContactIdentity.phone_hash,
                Patient.is_active.is_(True),
            )
        )
        is_new = ContactIdentity.was_known_patient.is_(False) & ~patient_exists
        row = (await self.session.execute(
            select(
                func.count(ContactIdentity.id).filter(is_new),
                func.count(ContactIdentity.id).filter(
                    is_new,
                    ContactIdentity.first_inbound_source == "kcell",
                ),
                func.count(ContactIdentity.id).filter(
                    is_new,
                    ContactIdentity.first_inbound_source == "whatsapp",
                ),
                func.count(ContactIdentity.id).filter(~is_new),
                func.max(ContactIdentity.updated_at),
            ).where(
                ContactIdentity.tenant_id == tenant_id,
                ContactIdentity.first_inbound_at >= start,
                ContactIdentity.first_inbound_at < end,
            )
        )).one()
        return tuple(int(value or 0) for value in row[:4]) + (row[4],)

    def _new_contact_filters(
        self, tenant_id: UUID, date_from: date, date_to: date, source: str | None = None
    ) -> list:
        start = clinic_day_start(date_from)
        end = clinic_day_end_exclusive(date_to)
        patient_exists = exists(
            select(Patient.id).where(
                Patient.tenant_id == tenant_id,
                Patient.phone_hash == ContactIdentity.phone_hash,
                Patient.is_active.is_(True),
            )
        )
        filters = [
            ContactIdentity.tenant_id == tenant_id,
            ContactIdentity.was_known_patient.is_(False),
            ~patient_exists,
            ContactIdentity.first_inbound_at >= start,
            ContactIdentity.first_inbound_at < end,
        ]
        if source:
            filters.append(ContactIdentity.first_inbound_source == source)
        return filters

    async def count_new_items(
        self, tenant_id: UUID, date_from: date, date_to: date, source: str | None = None
    ) -> int:
        return int(await self.session.scalar(
            select(func.count(ContactIdentity.id)).where(
                *self._new_contact_filters(tenant_id, date_from, date_to, source)
            )
        ) or 0)

    async def new_items(
        self,
        tenant_id: UUID,
        date_from: date,
        date_to: date,
        limit: int,
        *,
        offset: int = 0,
        source: str | None = None,
    ) -> list[ContactIdentity]:
        return list((await self.session.scalars(
            select(ContactIdentity).where(
                *self._new_contact_filters(tenant_id, date_from, date_to, source)
            ).order_by(ContactIdentity.first_inbound_at.desc()).offset(offset).limit(limit)
        )).all())
