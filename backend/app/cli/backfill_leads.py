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
    # Always look before you touch: prints exactly what a real run would do,
    # writes nothing.
    python -m app.cli.backfill_leads --tenant-slug san-dental --dry-run

    # The real run, once the dry-run output has been reviewed.
    python -m app.cli.backfill_leads --tenant-slug san-dental

    python -m app.cli.backfill_leads --all-tenants --dry-run

This is a manual, explicitly-invoked command -- it is never run automatically
on API startup or on every deploy (see render.yaml: the start command is only
`alembic upgrade head && uvicorn ...`). Run it from Render's Shell tab (or any
shell with DATABASE_URL pointing at the production database) after a deploy
that changes this backfill's logic, always dry-run first.

Rules (mirror the live lead-sync path where it still applies -- see
contacts/repository.py::sync_lead for the ongoing path, and
canonical_writer.py::_write_patient / reports/repository.py
::upsert_patient_identities for how a lead is won going forward):

- One normalized phone (its stored SHA-256 hash) = one Lead. This script
  never touches a plaintext phone number: Call.phone_hash and
  WhatsAppConversation.contact_hash are already-hashed columns, and nothing
  here decrypts a ciphertext or reads a raw phone field.

- Whether a contact becomes a Lead at all -- and what it becomes -- is
  decided by comparing the contact's *first* touch (first_contact_at, from
  merge_contact_events) against the matching Patient row's *first_visit_at*
  (when 1C first actually saw that person), never by whether a patient with
  that phone happens to exist *today* and never by Patient.is_active alone:

    * No Patient row shares this phone_hash at all -> a genuine, unmatched
      contact. "new" while last_contact_at is within LOST_LEAD_DAYS of the
      script's run time, "lost" once it has been silent longer -- the exact
      same cutoff sales/repository.py::reconcile_lost_leads uses going
      forward. patient_id/branch_id stay unset (nothing to attach).

    * A Patient row shares this phone_hash (active OR inactive -- 1C marking
      a patient inactive/deleted does not erase the fact that a real
      relationship already existed, so an old inactive patient must not be
      treated as if the phone had never been seen) and its first_visit_at is
      known and is *before* first_contact_at -> this person was already a
      1C patient before this contact ever happened. Not a lead. No Lead row
      is created at all.

    * A Patient row matches and its first_visit_at is known and is *at or
      after* first_contact_at -> the contact genuinely came first and the
      patient relationship followed. A real lead that won: status="won",
      patient_id/branch_id copied from that real 1C match, never guessed.
      If more than one Patient row shares the phone (a shared household
      number) and more than one qualifies, the one with the earliest
      first_visit_at is used -- the most-established real 1C appearance.

    * A Patient row matches but *no* matching row has a known first_visit_at
      -- 1C confirms the phone belongs to a real patient but never told us
      when they first appeared, so the order of events cannot be
      established. This is a deliberate, conservative fallback for
      older/incomplete snapshots (the v18 extension always sends
      first_visit_at going forward): rather than guess in either direction
      -- which could inflate "won" just as easily as it could inflate
      "new"/"lost" -- no Lead row is created. See resolve_lead_outcome.

  See resolve_lead_outcome for the pure, unit-tested implementation of all
  of the above.

- assigned_user_id is resolved from the *first* contact's channel only (a
  later contact on a different channel never overrides who first took the
  inquiry) via resolve_assignment (app.modules.sales.lead_assignment -- the
  same resolution the live inbound path uses in
  ContactRepository.sync_lead, so a Kcell extension or WhatsApp
  conversation is never interpreted two different ways depending on
  whether the contact came in live or through this backfill), using only
  real, explicit signals -- never approximate/fuzzy full-name matching:

    * Kcell: looked up in kcell_extension_assignments, an explicit,
      administrator-maintained mapping from Call.external_user (Kcell's own
      raw agent/extension string) to a User. No row for that extension at
      all -> "unresolved" (never configured). A row that exists but has
      assigned_user_id=NULL -> "ambiguous" (administrator explicitly marked
      this extension as shared/no single owner, e.g. a front-desk line).

    * WhatsApp: there is no per-message responsible-employee field, only
      WhatsAppConversation.assigned_user_id -- current "who's handling this
      now" state, not first-contact history. Used only as a best-effort
      proxy when it happens to be set at backfill time; otherwise
      "unresolved". This limitation is intentional and documented, not an
      oversight -- WhatsApp genuinely carries no better signal today.

  assignment_status ("assigned" / "unresolved" / "ambiguous") is tracked
  purely for the printed backfill statistics -- it is never itself stored.

- INSERT ... ON CONFLICT (tenant_id, external_id) DO NOTHING: a Lead that
  already exists (created by the live webhook path, an earlier run of this
  same script, or already won via a 1C patient snapshot) is never touched
  or overwritten. Re-running this script is a pure no-op for every phone
  already covered -- safe to run as many times as needed.

- --dry-run computes and prints every statistic below without writing a
  single row (the session is never asked to commit any Lead insert).

- Every table this script reads or writes (calls, patients, leads,
  whatsapp_conversations, kcell_extension_assignments) has
  FORCE ROW LEVEL SECURITY. backfill_tenant sets the transaction-local
  `app.tenant_id` GUC (the same `AuthRepository.set_tenant_context` used by
  the request path and by app/cli/create_initial_owner.py) as its very
  first action, before any tenant-scoped SELECT -- without this, RLS
  silently returns zero rows (a --dry-run would report contacts_scanned: 0
  even on a populated tenant) rather than raising. Because
  set_config(..., true) is transaction-local, it is cleared by _run's
  per-tenant commit()/rollback() and re-set from scratch by the next
  tenant's backfill_tenant call -- context is never carried over between
  tenants. RLS is never disabled and row_security is never turned off.

- Each phone_hash's read-decide-write sequence runs inside its own
  `session.begin_nested()` (a real SQL SAVEPOINT). If anything in it raises
  -- most likely a constraint violation on the write -- only that
  savepoint is rolled back; PostgreSQL never sees the outer, per-tenant
  transaction as aborted, so every remaining phone_hash and the final
  commit still proceed normally. Without this, one bad row would poison
  the whole transaction (any statement after it fails with "current
  transaction is aborted") and silently drop the rest of the tenant.
  phone_hash is never written to stdout/stderr, not even truncated -- a
  failure is logged by its position in this run (`contact #N`) only.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionFactory
from app.modules.auth.repository import AuthRepository
from app.modules.sales.lead_assignment import (
    load_kcell_assignment_map,
    load_whatsapp_current_assignment,
    resolve_assignment,
)
from app.modules.sales.models import Call, Lead, Patient
from app.modules.sales.repository import LOST_LEAD_DAYS
from app.modules.tenancy.models import Tenant
from app.modules.whatsapp.models import WhatsAppConversation, WhatsAppMessage

_INBOUND_CALL_DIRECTIONS = ("in", "incoming", "inbound", "входящий")

# The exact fields every dry-run and real run reports, in this order --
# see the module docstring and the "controlled deployment" requirement this
# satisfies: a backfill run must always show contacts_scanned,
# skipped_existing_patients, won, new, lost, skipped_existing_leads,
# assigned, unresolved_assignment, ambiguous_assignment, errors.
STAT_FIELDS = (
    "contacts_scanned",
    "skipped_existing_patients",
    "won",
    "new",
    "lost",
    "skipped_existing_leads",
    "assigned",
    "unresolved_assignment",
    "ambiguous_assignment",
    "errors",
)


@dataclass
class ContactAggregate:
    first_at: datetime
    first_source: str
    last_at: datetime
    # Call.external_user at the first-touching event, ONLY when
    # first_source == "kcell" -- the raw signal resolve_assignment needs.
    # Always None when the first contact was WhatsApp (that channel's
    # assignment signal is looked up separately, by phone, since it is
    # current-state rather than per-event).
    first_external_user: str | None = None


@dataclass(frozen=True)
class PatientMatch:
    patient_id: UUID
    branch_id: UUID | None
    first_visit_at: datetime | None


def merge_contact_events(
    events: list[tuple[str, str, datetime, str | None]],
) -> dict[str, ContactAggregate]:
    """Pure aggregation: group (phone_hash, source, occurred_at,
    external_user) events -- phone_hash already-hashed, never plaintext --
    into one first/last-contact record per phone_hash. The earliest
    occurred_at across every channel wins "first source" (and, if that
    first source is Kcell, its external_user); the latest wins last_at. A
    repeat contact on the same channel, or a later contact on the other
    channel, updates last_at without creating a second entry -- there is
    exactly one aggregate per phone_hash no matter how many events
    reference it.
    """
    merged: dict[str, ContactAggregate] = {}
    for phone_hash, source, occurred_at, external_user in events:
        current = merged.get(phone_hash)
        if current is None:
            merged[phone_hash] = ContactAggregate(
                first_at=occurred_at,
                first_source=source,
                last_at=occurred_at,
                first_external_user=external_user if source == "kcell" else None,
            )
            continue
        if occurred_at < current.first_at:
            current.first_at = occurred_at
            current.first_source = source
            current.first_external_user = external_user if source == "kcell" else None
        if occurred_at > current.last_at:
            current.last_at = occurred_at
    return merged


def resolve_lead_outcome(
    *,
    patient_matches: list[PatientMatch],
    first_contact_at: datetime,
    last_contact_at: datetime,
    now: datetime,
) -> tuple[str, UUID | None, UUID | None] | None:
    """Pure decision: how a historical contact should become a Lead, or
    None when it must not become a Lead at all. See the module docstring
    for the full rationale; this is its direct, unit-tested implementation.
    """
    dated_matches = [m for m in patient_matches if m.first_visit_at is not None]
    if patient_matches and not dated_matches:
        # Matched a real patient, but none of the matches carry a usable
        # first_visit_at -- cannot establish contact-vs-visit order.
        # Conservative default: not a lead, rather than guess.
        return None
    pre_existing = [m for m in dated_matches if m.first_visit_at < first_contact_at]
    if pre_existing:
        # At least one matching patient already existed in 1C before this
        # contact -- treat the whole phone_hash as an existing relationship,
        # even if another match on the same shared number looks newer.
        return None
    if dated_matches:
        won_match = min(dated_matches, key=lambda m: m.first_visit_at)
        return "won", won_match.patient_id, won_match.branch_id
    if now - last_contact_at >= timedelta(days=LOST_LEAD_DAYS):
        return "lost", None, None
    return "new", None, None


# resolve_assignment is imported from app.modules.sales.lead_assignment (not
# defined here) so its exact decision rule -- Kcell external_user ->
# assigned_user_id, WhatsApp current-conversation proxy, never fuzzy -- is
# the same one the live inbound path (ContactRepository.sync_lead) uses,
# rather than two independently-maintained copies of the same logic. It
# stays importable as `backfill_leads.resolve_assignment` (see the import
# above) so nothing else in this codebase needs to change.


async def _collect_events(
    session: AsyncSession, tenant_id: UUID
) -> list[tuple[str, str, datetime, str | None]]:
    events: list[tuple[str, str, datetime, str | None]] = []
    call_rows = await session.execute(
        select(Call.phone_hash, Call.started_at, Call.external_user).where(
            Call.tenant_id == tenant_id,
            func.lower(Call.direction).in_(_INBOUND_CALL_DIRECTIONS),
        )
    )
    events.extend(
        (phone_hash, "kcell", started_at, external_user)
        for phone_hash, started_at, external_user in call_rows
    )

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
        (contact_hash, "whatsapp", occurred_at, None) for contact_hash, occurred_at in message_rows
    )
    return events


async def _patient_matches_by_hash(
    session: AsyncSession, tenant_id: UUID, phone_hashes: set[str]
) -> dict[str, list[PatientMatch]]:
    """Fetches every Patient row (active or inactive -- see the module
    docstring on why is_active must never gate this) sharing any of the
    given phone hashes, in one query, grouped by phone_hash.
    """
    if not phone_hashes:
        return {}
    rows = (
        await session.execute(
            select(Patient.phone_hash, Patient.id, Patient.branch_id, Patient.first_visit_at).where(
                Patient.tenant_id == tenant_id,
                Patient.phone_hash.in_(phone_hashes),
            )
        )
    ).all()
    result: dict[str, list[PatientMatch]] = {}
    for phone_hash, patient_id, branch_id, first_visit_at in rows:
        result.setdefault(phone_hash, []).append(
            PatientMatch(patient_id=patient_id, branch_id=branch_id, first_visit_at=first_visit_at)
        )
    return result


async def _kcell_assignment_map(session: AsyncSession, tenant_id: UUID) -> dict[str, UUID | None]:
    """Thin wrapper around the shared, tenant-scoped loader -- kept as a
    module-level name (rather than calling load_kcell_assignment_map
    directly from backfill_tenant) purely so existing tests can keep
    monkeypatching `backfill_leads._kcell_assignment_map` unchanged. No
    filter: backfill processes every historical contact for the tenant in
    one pass, so it needs the whole map up front, unlike the live path
    (see app.modules.sales.lead_assignment.resolve_new_lead_assigned_user_id),
    which resolves one contact -- and therefore one extension -- at a time.
    """
    return await load_kcell_assignment_map(session, tenant_id)


async def _whatsapp_current_assignment(session: AsyncSession, tenant_id: UUID) -> dict[str, UUID | None]:
    """Thin wrapper around the shared, tenant-scoped loader -- see
    _kcell_assignment_map's docstring for why this stays a module-level
    name instead of calling load_whatsapp_current_assignment directly.
    """
    return await load_whatsapp_current_assignment(session, tenant_id)


async def backfill_tenant(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    # Every query below hits an RLS-protected (FORCE ROW LEVEL SECURITY)
    # table -- this must be the first thing that touches `session` for this
    # tenant, or every tenant-scoped SELECT below silently returns zero rows
    # instead of raising (RLS filters, it doesn't error). Transaction-local
    # (set_config(..., true)): cleared by the caller's commit()/rollback(),
    # re-set here again for the next tenant's call.
    await AuthRepository(session).set_tenant_context(tenant_id)

    now = now or datetime.now(UTC)
    events = await _collect_events(session, tenant_id)
    aggregates = merge_contact_events(events)

    patient_matches = await _patient_matches_by_hash(session, tenant_id, set(aggregates))
    kcell_assignments = await _kcell_assignment_map(session, tenant_id)
    whatsapp_assignments = await _whatsapp_current_assignment(session, tenant_id)

    totals = {field: 0 for field in STAT_FIELDS}
    totals["contacts_scanned"] = len(aggregates)

    for index, (phone_hash, aggregate) in enumerate(aggregates.items()):
        try:
            # A real SQL SAVEPOINT for this phone_hash alone -- see the
            # module docstring. If anything below raises, only this
            # savepoint rolls back; the outer per-tenant transaction (and
            # every phone_hash already processed in it) is unaffected, so
            # the loop can safely continue and the final commit still
            # succeeds.
            async with session.begin_nested():
                existing_lead = await session.scalar(
                    select(Lead.id).where(Lead.tenant_id == tenant_id, Lead.external_id == phone_hash)
                )
                if existing_lead is not None:
                    totals["skipped_existing_leads"] += 1
                    continue

                outcome = resolve_lead_outcome(
                    patient_matches=patient_matches.get(phone_hash, []),
                    first_contact_at=aggregate.first_at,
                    last_contact_at=aggregate.last_at,
                    now=now,
                )
                if outcome is None:
                    totals["skipped_existing_patients"] += 1
                    continue
                status, patient_id, branch_id = outcome

                assigned_user_id, assignment_status = resolve_assignment(
                    first_source=aggregate.first_source,
                    first_external_user=aggregate.first_external_user,
                    kcell_assignment_by_extension=kcell_assignments,
                    whatsapp_current_assigned_user_id=whatsapp_assignments.get(phone_hash),
                )
                if assignment_status == "assigned":
                    totals["assigned"] += 1
                elif assignment_status == "ambiguous":
                    totals["ambiguous_assignment"] += 1
                elif assignment_status == "unresolved":
                    totals["unresolved_assignment"] += 1

                if dry_run:
                    totals[status] += 1
                    continue

                statement = (
                    pg_insert(Lead)
                    .values(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        branch_id=branch_id,
                        patient_id=patient_id,
                        assigned_user_id=assigned_user_id,
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
                    # Lost the race against a concurrent writer (live
                    # webhook, or another instance of this same script)
                    # between our existing-lead check and the insert --
                    # not an error.
                    totals["skipped_existing_leads"] += 1
        except Exception as exc:  # noqa: BLE001 -- one bad phone must not abort the whole tenant
            totals["errors"] += 1
            # Never phone_hash, not even truncated -- position in this run
            # only, so a bad record is still findable without ever writing
            # PII-adjacent material to a log.
            print(f"[backfill_leads] error processing contact #{index}: {exc}", file=sys.stderr)
    return totals


def _merge_totals(into: dict[str, int], part: dict[str, int]) -> None:
    for key, value in part.items():
        into[key] = into.get(key, 0) + value


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
        totals = {field: 0 for field in STAT_FIELDS}
        for tenant_id in tenant_ids:
            result = await backfill_tenant(session, tenant_id, dry_run=args.dry_run)
            _merge_totals(totals, result)
            if args.dry_run:
                await session.rollback()
            else:
                await session.commit()
        mode = "DRY RUN (no rows written)" if args.dry_run else "REAL RUN (rows written)"
        print(f"backfill_leads -- {mode} -- {len(tenant_ids)} tenant(s)")
        for field in STAT_FIELDS:
            print(f"  {field}: {totals[field]}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tenant-slug", help="Backfill one tenant by slug")
    group.add_argument("--all-tenants", action="store_true", help="Backfill every active tenant")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print every statistic without writing a single Lead row.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(_run(parse_args()))
