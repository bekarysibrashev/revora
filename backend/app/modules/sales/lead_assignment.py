"""Single source of truth for "who is responsible for this Lead".

Resolves an assigned_user_id from a Kcell agent extension
(kcell_extension_assignments, an explicit administrator-maintained mapping
-- see app.modules.kcell.models.KcellExtensionAssignment) or from a WhatsApp
conversation's current assignment state. Never by fuzzy/full-name matching.

Used by both:
- the live inbound path -- app.modules.contacts.repository.ContactRepository
  .sync_lead, reached from both the Kcell webhook (kcell/router.py) and the
  WhatsApp webhook (whatsapp/router.py -> whatsapp/service.py), always via
  ContactRegistry.register_inbound;
- app.cli.backfill_leads, for historical contacts that predate this code.

Before this module existed, the same "Kcell external_user ->
assigned_user_id" resolution was implemented twice -- once here (well,
where this module's predecessor lived, inside backfill_leads.py) and,
separately, the live path never consulted kcell_extension_assignments at
all, so every Kcell-sourced Lead created by the live webhook kept
assigned_user_id=None forever regardless of what an administrator had
configured via app.cli.manage_kcell_assignments. Consolidating the
resolution logic here and wiring ContactRepository.sync_lead to use it
closes that gap without duplicating the mapping/decision rules a second
time.

Nothing here decides *whether* a contact becomes a Lead at all -- that is
a separate concern (resolve_lead_outcome, backfill-only; the live path's
own simpler "new/lost -> new" rule lives directly in
ContactRepository.sync_lead) -- only, given that it does, who it should be
assigned to.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.kcell.models import KcellExtensionAssignment
from app.modules.whatsapp.models import WhatsAppConversation


def resolve_assignment(
    *,
    first_source: str,
    first_external_user: str | None,
    kcell_assignment_by_extension: dict[str, UUID | None],
    whatsapp_current_assigned_user_id: UUID | None,
) -> tuple[UUID | None, str]:
    """Pure decision: (assigned_user_id, assignment_status) for a Lead, from
    one contact's channel and (for Kcell) its external_user. assignment_status
    is one of "assigned", "unresolved", "ambiguous", "not_applicable" -- for
    backfill's printed statistics; callers that only need the assigned_user_id
    (the live path) can ignore it, since both "unresolved" and "ambiguous"
    already resolve assigned_user_id to None.

    * Kcell: looked up in kcell_assignment_by_extension, an explicit,
      administrator-maintained mapping from Call.external_user (Kcell's own
      raw agent/extension string) to a User. No row for that extension at
      all -> "unresolved" (never configured). A row that exists but has
      assigned_user_id=NULL -> "ambiguous" (administrator explicitly marked
      this extension as shared/no single owner, e.g. a front-desk line).

    * WhatsApp: there is no per-message responsible-employee field, only
      WhatsAppConversation.assigned_user_id -- current "who's handling this
      now" state, not first-contact history. Used only as a best-effort
      proxy when it happens to be set at resolution time; otherwise
      "unresolved". For a brand-new WhatsApp contact this is honestly
      "unresolved" every time: the conversation itself is only created
      *after* the live path first registers the inbound (see
      ContactRepository.sync_lead's docstring), so there is no assignment
      yet to read.
    """
    if first_source == "kcell":
        if first_external_user is None:
            return None, "unresolved"
        if first_external_user not in kcell_assignment_by_extension:
            return None, "unresolved"
        mapped = kcell_assignment_by_extension[first_external_user]
        return (mapped, "assigned") if mapped is not None else (None, "ambiguous")
    if first_source == "whatsapp":
        if whatsapp_current_assigned_user_id is not None:
            return whatsapp_current_assigned_user_id, "assigned"
        return None, "unresolved"
    return None, "not_applicable"


async def load_kcell_assignment_map(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    external_users: set[str] | None = None,
) -> dict[str, UUID | None]:
    """Tenant-scoped external_user -> assigned_user_id map from
    kcell_extension_assignments. A missing key means "never configured"
    (unresolved); a key present with value None means an administrator
    explicitly marked that extension as shared/no single owner (ambiguous).

    Pass `external_users` to scope the query to one or a few extensions --
    the live path resolves exactly one contact at a time and should not pay
    for loading a whole tenant's mapping table per webhook call. Omit it to
    load the whole tenant's map in one query -- app.cli.backfill_leads,
    which processes every historical contact in a single pass, needs the
    whole map anyway and would otherwise issue one query per phone_hash.

    Always filtered by tenant_id, so an extension configured for a
    different tenant can never be returned here, however it is called --
    kcell_extension_assignments also carries FORCE ROW LEVEL SECURITY, so
    this is a second, independent layer of the same guarantee, not the
    only one.
    """
    statement = select(
        KcellExtensionAssignment.external_user, KcellExtensionAssignment.assigned_user_id
    ).where(KcellExtensionAssignment.tenant_id == tenant_id)
    if external_users is not None:
        statement = statement.where(KcellExtensionAssignment.external_user.in_(external_users))
    rows = await session.execute(statement)
    return {external_user: assigned_user_id for external_user, assigned_user_id in rows}


async def load_whatsapp_current_assignment(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    contact_hashes: set[str] | None = None,
) -> dict[str, UUID | None]:
    """Tenant-scoped contact_hash -> assigned_user_id map from the
    *current* state of whatsapp_conversations -- not per-message history,
    since WhatsApp carries no per-message responsible-employee field (see
    resolve_assignment's docstring). A phone can have more than one
    conversation row (different channel_id); if any of them currently has
    a human assigned, that wins.

    Pass `contact_hashes` to scope to one phone (the live path, one contact
    at a time); omit it to load the whole tenant at once
    (app.cli.backfill_leads).
    """
    statement = select(
        WhatsAppConversation.contact_hash, WhatsAppConversation.assigned_user_id
    ).where(WhatsAppConversation.tenant_id == tenant_id)
    if contact_hashes is not None:
        statement = statement.where(WhatsAppConversation.contact_hash.in_(contact_hashes))
    rows = await session.execute(statement)
    result: dict[str, UUID | None] = {}
    for contact_hash, assigned_user_id in rows:
        if assigned_user_id is not None:
            result[contact_hash] = assigned_user_id
        else:
            result.setdefault(contact_hash, None)
    return result


async def resolve_new_lead_assigned_user_id(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    source: str,
    phone_hash: str,
    external_user: str | None = None,
) -> UUID | None:
    """The single, shared answer to "who should a brand-new Lead from this
    contact be assigned to". Issues exactly one tenant-scoped query (Kcell:
    kcell_extension_assignments filtered to this one external_user;
    WhatsApp: whatsapp_conversations filtered to this one phone_hash), then
    reuses the same resolve_assignment decision app.cli.backfill_leads
    relies on for historical contacts -- so a Kcell extension or a WhatsApp
    conversation is never interpreted two different ways depending on
    whether the contact came in live or through a backfill.

    The caller is responsible for RLS/tenant context (app.tenant_id)
    already being set on `session` before this is called -- this function
    issues ordinary tenant-scoped SELECTs, nothing more. Both live-path
    callers (ContactRepository.sync_lead, reached from kcell/router.py and
    whatsapp/router.py) already run after that context is established.
    """
    kcell_assignment_by_extension: dict[str, UUID | None] = {}
    whatsapp_current_assigned_user_id: UUID | None = None
    if source == "kcell" and external_user is not None:
        kcell_assignment_by_extension = await load_kcell_assignment_map(
            session, tenant_id, external_users={external_user}
        )
    elif source == "whatsapp":
        whatsapp_map = await load_whatsapp_current_assignment(
            session, tenant_id, contact_hashes={phone_hash}
        )
        whatsapp_current_assigned_user_id = whatsapp_map.get(phone_hash)
    assigned_user_id, _status = resolve_assignment(
        first_source=source,
        first_external_user=external_user,
        kcell_assignment_by_extension=kcell_assignment_by_extension,
        whatsapp_current_assigned_user_id=whatsapp_current_assigned_user_id,
    )
    return assigned_user_id
