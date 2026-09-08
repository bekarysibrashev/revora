from datetime import date, datetime
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts.models import ContactIdentity
from app.modules.kcell.models import KcellWebhookReceipt
from app.modules.sales.lead_assignment import resolve_new_lead_assigned_user_id
from app.modules.sales.models import Call, Lead, Patient
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

    async def sync_lead(
        self,
        *,
        tenant_id: UUID,
        phone_hash: str,
        classification: str,
        source: str,
        occurred_at: datetime,
        external_user: str | None = None,
    ) -> None:
        """Materialize or touch a prospect from a real inbound contact -- the
        single live-path entry point for both the Kcell webhook
        (kcell/router.py) and the WhatsApp webhook (whatsapp/router.py ->
        whatsapp/service.py), always reached through
        ContactRegistry.register_inbound / ._sync_lead. This is, and must
        stay, the only place a Lead is created or touched from live
        traffic: a second call creating/touching a Lead for the same event
        would race this one under autoflush=False (see
        core/database.py::AsyncSessionFactory) -- neither call's
        select(Lead) would see the other's still-unflushed INSERT, so both
        would try to insert a Lead for the same (tenant_id, external_id),
        violating its unique constraint at the next flush and failing the
        whole webhook for every brand-new prospect.

        Known 1C patients are deliberately excluded. The normalized phone
        hash is the stable cross-channel key, so a Kcell call and WhatsApp
        message for the same person update one lead instead of duplicating it.

        assigned_user_id is resolved via
        app.modules.sales.lead_assignment.resolve_new_lead_assigned_user_id
        -- the same resolution app.cli.backfill_leads uses for historical
        contacts -- but only ever *fills in* a responsible employee, never
        overwrites one:
        - a brand-new Lead gets whatever resolve_new_lead_assigned_user_id
          returns (a real mapping, or None if unresolved/ambiguous);
        - an existing Lead that already has an assigned_user_id is left
          alone -- a later call/message must never silently reassign it;
        - an existing Lead with assigned_user_id still None gets one filled
          in if this contact resolves to an unambiguous owner; an
          unresolved/ambiguous resolution (None) never clears anything,
          because there is nothing to clear;
        - a "won" Lead is untouched entirely (see below), including its
          assigned_user_id -- retroactively assigning a already-won lead is
          a separate, larger decision this method does not make.
        """
        if classification in {"existing_1c_patient", "unknown_patient"}:
            return
        lead = await self.session.scalar(
            select(Lead).where(
                Lead.tenant_id == tenant_id,
                Lead.external_id == phone_hash,
            )
        )
        if lead is None:
            assigned_user_id = await resolve_new_lead_assigned_user_id(
                self.session,
                tenant_id,
                source=source,
                phone_hash=phone_hash,
                external_user=external_user,
            )
            self.session.add(Lead(
                tenant_id=tenant_id,
                branch_id=None,
                patient_id=None,
                assigned_user_id=assigned_user_id,
                external_id=phone_hash,
                source=source,
                status="new",
                last_contact_at=occurred_at,
            ))
            return
        if lead.status == "won":
            # Already a real patient -- a later call/message does not reopen
            # the funnel, and does not touch assigned_user_id either, even
            # if it is still None. Won stays fully terminal.
            return
        lead.last_contact_at = max(lead.last_contact_at, occurred_at)
        if lead.status == "lost":
            lead.status = "new"
        if lead.assigned_user_id is None:
            assigned_user_id = await resolve_new_lead_assigned_user_id(
                self.session,
                tenant_id,
                source=source,
                phone_hash=phone_hash,
                external_user=external_user,
            )
            if assigned_user_id is not None:
                lead.assigned_user_id = assigned_user_id

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
