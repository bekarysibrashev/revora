"""One-off, safely re-runnable backfill: materialize sales.Lead rows for
historical Kcell calls / WhatsApp messages that predate ContactRegistry's
live lead-sync wiring, or that were simply never touched by it because the
event happened before this code existed.

This does NOT depend on anyone ever opening the "Новые обращения" page --
that page's own historical materialization (see
contacts/service.py::ContactService._materialize_history) only ever creates
ContactIdentity rows for whatever date range someone happened to view, and
even then it never touches sales.Lead at all. This script reads Call and
WhatsAppMessage/WhatsAppConversation directly, for all of a tenant's history
in one pass, and is the only thing that turns old contacts into Leads.

Usage:
    python -m app.cli.backfill_leads --tenant-slug san-dental
    python -m app.cli.backfill_leads --all-tenants

Rules (mirror the live lead-sync path exactly -- see
contacts/repository.py::sync_lead for the ongoing path, and
canonical_writer.py::_write_patient / reports/repository.py
::upsert_patient_identities for how a lead is won going forward):

- One normalized phone (its stored SHA-256 hash) = one Lead. This script
  never touches a plaintext phone number: Call.phone_hash and
  WhatsAppConversation.contact_hash are already-hashed columns, and nothing
  here decrypts a ciphertext or reads a raw phone field.
- A phone_hash that is currently an active Patient's phone_hash gets a Lead
  that starts life already "won" (a real historical contact genuinely
  happened, it just also happens to already be a known patient today): the
  matched Patient becomes patient_id and its branch_id is copied across --
  both grounded in a real 1C match, never guessed. Everything else becomes
  "new" (last contact inside the LOST_LEAD_DAYS window as of when this
  script runs) or "lost" (silent for that long already) -- the exact same
  cutoff sales/repository.py::reconcile_lost_leads uses going forward.
- assigned_user_id is never set: none of Call, WhatsAppMessage or 1C carries
  a responsible employee for a historical contact, so it stays unassigned
  rather than guessed.
- INSERT ... ON CONFLICT (tenant_id, external_id) DO NOTHING: a Lead that
  already exists (created by the live webhook path, an earlier run of this
  same script, or already won via a 1C patient snapshot) is never touched
  or overwritten. Re-running this script is a pure no-op for every phone
  already covered -- safe to run as many times as needed.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionFactory
from app.modules.sales.models import Call, Lead, Patient
from app.modules.sales.repository import LOST_LEAD_DAYS
from app.modules.tenancy.models import Tenant
from app.modules.whatsapp.models import WhatsAppConversation, WhatsAppMessage

_INBOUND_CALL_DIRECTIONS = ("in", "incoming", "inbound", "входящий")


@dataclass
class ContactAggregate:
    first_at: datetime
    first_source: str
    last_at: datetime


def merge_contact_events(
    events: list[tuple[str, str, datetime]],
) -> dict[str, ContactAggregate]:
    """Pure aggregation: group (phone_hash, source, occurred_at) triples --
    already-hashed, never plaintext -- into one first/last-contact record
    per phone_hash. The earliest occurred_at across every channel wins the
    "first source"; the latest wins last_at. A repeat contact on the same
    channel, or a later contact on the other channel, updates last_at
    without creating a second entry -- there is exactly one aggregate per
    phone_hash no matter how many events reference it.
    """
    merged: dict[str, ContactAggregate] = {}
    for phone_hash, source, occurred_at in events:
        current = merged.get(phone_hash)
        if current is None:
            merged[phone_hash] = ContactAggregate(
                first_at=occurred_at, first_source=source, last_at=occurred_at
            )
            continue
        if occurred_at < current.first_at:
            current.first_at = occurred_at
            current.first_source = source
        if occurred_at > current.last_at:
            current.last_at = occurred_at
    return merged


def decide_lead_state(
    *,
    matched_patient_id: UUID | None,
    matched_patient_branch_id: UUID | None,
    last_contact_at: datetime,
    now: datetime,
) -> tuple[str, UUID | None, UUID | None]:
    """Pure decision: the (status, patient_id, branch_id) a backfilled Lead
    should start with. Never invents a branch -- branch_id is populated only
    when a real Patient row was matched, otherwise it stays None, exactly
    the same rule the live "won" writers use.
    """
    if matched_patient_id is not None:
        return "won", matched_patient_id, matched_patient_branch_id
    if now - last_contact_at >= timedelta(days=LOST_LEAD_DAYS):
        return "lost", None, None
    return "new", None, None


async def _collect_events(
    session: AsyncSession, tenant_id: UUID
) -> list[tuple[str, str, datetime]]:
    events: list[tuple[str, str, datetime]] = []
    call_rows = await session.execute(
        select(Call.phone_hash, Call.started_at).where(
            Call.tenant_id == tenant_id,
            func.lower(Call.direction).in_(_INBOUND_CALL_DIRECTIONS),
        )
    )
    events.extend((phone_hash, "kcell", started_at) for phone_hash, started_at in call_rows)

    message_rows = await session.execute(
        select(
            WhatsAppConversation.contact_hash,
            func.coalesce(WhatsAppMessage.provider_timestamp, WhatsAppMessage.created_at),
        )
        .join(WhatsAppMessage, WhatsAppMessage.conversation_id == WhatsAppConversation.id)
        .where(
            WhatsAppConversation.tenant_id == tenant_id,
            WhatsAppMessage.direction == "in",
        )
    )
    events.extend(
        (contact_hash, "whatsapp", occurred_at) for contact_hash, occurred_at in message_rows
    )
    return events


async def backfill_tenant(
    session: AsyncSession, tenant_id: UUID, *, now: datetime | None = None
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    events = await _collect_events(session, tenant_id)
    aggregates = merge_contact_events(events)

    totals = {"won": 0, "new": 0, "lost": 0, "skipped_existing": 0}
    for phone_hash, aggregate in aggregates.items():
        existing_lead = await session.scalar(
            select(Lead.id).where(Lead.tenant_id == tenant_id, Lead.external_id == phone_hash)
        )
        if existing_lead is not None:
            totals["skipped_existing"] += 1
            continue
        patient_row = (
            await session.execute(
                select(Patient.id, Patient.branch_id).where(
                    Patient.tenant_id == tenant_id,
                    Patient.phone_hash == phone_hash,
                    Patient.is_active.is_(True),
                )
            )
        ).first()
        status, patient_id, branch_id = decide_lead_state(
            matched_patient_id=patient_row[0] if patient_row else None,
            matched_patient_branch_id=patient_row[1] if patient_row else None,
            last_contact_at=aggregate.last_at,
            now=now,
        )
        statement = (
            pg_insert(Lead)
            .values(
                id=uuid4(),
                tenant_id=tenant_id,
                branch_id=branch_id,
                patient_id=patient_id,
                assigned_user_id=None,
                external_id=phone_hash,
                source=aggregate.first_source,
                status=status,
                last_contact_at=aggregate.last_at,
                created_at=aggregate.first_at,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "external_id"])
        )
        result = await session.execute(statement)
        if result.rowcount:
            totals[status] += 1
        else:
            # Lost the race against a concurrent writer (live webhook,
            # or another instance of this same script) between our
            # existing-lead check and the insert -- not an error.
            totals["skipped_existing"] += 1
    return totals


async def _run(args: argparse.Namespace) -> None:
    async with AsyncSessionFactory() as session:
        if args.tenant_slug:
            tenant_id = await session.scalar(
                select(Tenant.id).where(Tenant.slug == args.tenant_slug)
            )
            if tenant_id is None:
                raise SystemExit(f"Unknown tenant slug: {args.tenant_slug}")
            tenant_ids = [tenant_id]
        else:
            tenant_ids = list(
                (await session.scalars(select(Tenant.id).where(Tenant.is_active.is_(True)))).all()
            )
        totals = {"won": 0, "new": 0, "lost": 0, "skipped_existing": 0}
        for tenant_id in tenant_ids:
            result = await backfill_tenant(session, tenant_id)
            for key, value in result.items():
                totals[key] += value
            await session.commit()
        print(
            f"Backfilled {len(tenant_ids)} tenant(s): "
            f"{totals['won']} won, {totals['new']} new, {totals['lost']} lost, "
            f"{totals['skipped_existing']} already present (untouched)."
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tenant-slug", help="Backfill one tenant by slug")
    group.add_argument("--all-tenants", action="store_true", help="Backfill every active tenant")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(_run(parse_args()))
