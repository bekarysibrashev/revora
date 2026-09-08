"""Tests for the shared Kcell/WhatsApp -> assigned_user_id resolution
(app.modules.sales.lead_assignment) and for how ContactRepository.sync_lead
-- the single live-path entry point reached from both the Kcell and
WhatsApp webhooks -- uses it.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.contacts import repository as contacts_repository
from app.modules.contacts.repository import ContactRepository
from app.modules.sales import lead_assignment
from app.modules.sales.lead_assignment import (
    load_kcell_assignment_map,
    load_whatsapp_current_assignment,
    resolve_new_lead_assigned_user_id,
)
from app.modules.sales.models import Lead

EARLIER = datetime(2026, 6, 1, tzinfo=UTC)
LATER = datetime(2026, 6, 2, tzinfo=UTC)
PHONE_HASH = "a" * 64


def _lead(**overrides) -> Lead:
    defaults = dict(
        id=uuid4(),
        tenant_id=uuid4(),
        branch_id=None,
        patient_id=None,
        assigned_user_id=None,
        external_id=PHONE_HASH,
        source="kcell",
        status="new",
        last_contact_at=EARLIER,
    )
    defaults.update(overrides)
    return Lead(**defaults)


# ---------------------------------------------------------------------------
# resolve_new_lead_assigned_user_id -- the shared resolution itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_kcell_lead_with_configured_mapping_is_assigned(monkeypatch) -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    monkeypatch.setattr(
        lead_assignment,
        "load_kcell_assignment_map",
        AsyncMock(return_value={"101": user_id}),
    )

    result = await resolve_new_lead_assigned_user_id(
        AsyncMock(), tenant_id, source="kcell", phone_hash=PHONE_HASH, external_user="101"
    )

    assert result == user_id


@pytest.mark.asyncio
async def test_kcell_extension_never_configured_resolves_to_none(monkeypatch) -> None:
    """No row at all for this extension -- "unresolved"."""
    tenant_id = uuid4()
    monkeypatch.setattr(
        lead_assignment, "load_kcell_assignment_map", AsyncMock(return_value={})
    )

    result = await resolve_new_lead_assigned_user_id(
        AsyncMock(), tenant_id, source="kcell", phone_hash=PHONE_HASH, external_user="999"
    )

    assert result is None


@pytest.mark.asyncio
async def test_kcell_extension_marked_ambiguous_resolves_to_none(monkeypatch) -> None:
    """A row exists but assigned_user_id is NULL -- an administrator
    explicitly marked this extension as shared (see
    app.cli.manage_kcell_assignments mark-ambiguous). Also "no owner", but
    for a different, more informative reason than "never configured" --
    both must resolve the same way here (None), the distinction is only in
    resolve_assignment's own returned status, which backfill's stats use
    and the live path does not need."""
    tenant_id = uuid4()
    monkeypatch.setattr(
        lead_assignment,
        "load_kcell_assignment_map",
        AsyncMock(return_value={"front-desk": None}),
    )

    result = await resolve_new_lead_assigned_user_id(
        AsyncMock(), tenant_id, source="kcell", phone_hash=PHONE_HASH, external_user="front-desk"
    )

    assert result is None


@pytest.mark.asyncio
async def test_kcell_with_no_external_user_resolves_to_none_without_querying(monkeypatch) -> None:
    """A Kcell contact with no external_user (should not happen in
    practice, but the resolver must not guess) never even issues the
    lookup query."""
    load_mock = AsyncMock(return_value={"101": uuid4()})
    monkeypatch.setattr(lead_assignment, "load_kcell_assignment_map", load_mock)

    result = await resolve_new_lead_assigned_user_id(
        AsyncMock(), uuid4(), source="kcell", phone_hash=PHONE_HASH, external_user=None
    )

    assert result is None
    load_mock.assert_not_called()


@pytest.mark.asyncio
async def test_whatsapp_lead_gets_assigned_user_id_when_conversation_already_has_one(monkeypatch) -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    monkeypatch.setattr(
        lead_assignment,
        "load_whatsapp_current_assignment",
        AsyncMock(return_value={PHONE_HASH: user_id}),
    )

    result = await resolve_new_lead_assigned_user_id(
        AsyncMock(), tenant_id, source="whatsapp", phone_hash=PHONE_HASH, external_user=None
    )

    assert result == user_id


@pytest.mark.asyncio
async def test_whatsapp_first_ever_contact_has_no_conversation_yet_so_resolves_to_none(monkeypatch) -> None:
    """Honest limitation: WhatsAppConversation is only created *after*
    ContactRegistry.register_inbound first registers the contact (see
    ContactRepository.sync_lead's docstring and whatsapp/service.py's
    call order), so for a brand-new phone number there is genuinely no
    conversation row yet to read an assignment from."""
    tenant_id = uuid4()
    monkeypatch.setattr(
        lead_assignment, "load_whatsapp_current_assignment", AsyncMock(return_value={})
    )

    result = await resolve_new_lead_assigned_user_id(
        AsyncMock(), tenant_id, source="whatsapp", phone_hash=PHONE_HASH, external_user=None
    )

    assert result is None


@pytest.mark.asyncio
async def test_cross_tenant_kcell_mapping_is_never_applied(monkeypatch) -> None:
    """load_kcell_assignment_map is always tenant-scoped by construction
    (see its own SQL-shape test below); from resolve_new_lead_assigned_user_id's
    point of view, an extension configured for a *different* tenant is
    indistinguishable from "never configured" -- the scoped map simply
    will not contain it, exactly as if this tenant had never set it."""
    tenant_id = uuid4()
    other_tenants_map = AsyncMock(return_value={})  # this tenant's scoped query finds nothing
    monkeypatch.setattr(lead_assignment, "load_kcell_assignment_map", other_tenants_map)

    result = await resolve_new_lead_assigned_user_id(
        AsyncMock(), tenant_id, source="kcell", phone_hash=PHONE_HASH, external_user="101"
    )

    assert result is None
    other_tenants_map.assert_called_once()
    assert other_tenants_map.call_args.args[1] == tenant_id


# ---------------------------------------------------------------------------
# load_kcell_assignment_map / load_whatsapp_current_assignment -- the
# actual SQL shape, so tenant-scoping is verified against the real query
# building code, not just re-asserted by a mock.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_kcell_assignment_map_query_is_scoped_to_tenant_id() -> None:
    tenant_id = uuid4()
    session = AsyncMock()
    result = MagicMock()
    result.__iter__ = lambda self: iter([("101", uuid4())])
    session.execute = AsyncMock(return_value=result)

    await load_kcell_assignment_map(session, tenant_id, external_users={"101"})

    statement = session.execute.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": False}))
    assert "kcell_extension_assignments.tenant_id" in compiled


@pytest.mark.asyncio
async def test_load_whatsapp_current_assignment_query_is_scoped_to_tenant_id() -> None:
    tenant_id = uuid4()
    session = AsyncMock()
    result = MagicMock()
    result.__iter__ = lambda self: iter([(PHONE_HASH, uuid4())])
    session.execute = AsyncMock(return_value=result)

    await load_whatsapp_current_assignment(session, tenant_id, contact_hashes={PHONE_HASH})

    statement = session.execute.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": False}))
    assert "whatsapp_conversations.tenant_id" in compiled


# ---------------------------------------------------------------------------
# ContactRepository.sync_lead -- the live-path orchestration rules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_lead_creates_new_lead_with_resolved_assigned_user_id(monkeypatch) -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)  # no existing lead
    session.add = MagicMock()
    resolve_mock = AsyncMock(return_value=user_id)
    monkeypatch.setattr(contacts_repository, "resolve_new_lead_assigned_user_id", resolve_mock)
    repo = ContactRepository(session)

    await repo.sync_lead(
        tenant_id=tenant_id,
        phone_hash=PHONE_HASH,
        classification="new_contact",
        source="kcell",
        occurred_at=EARLIER,
        external_user="101",
    )

    session.add.assert_called_once()
    added_lead = session.add.call_args.args[0]
    assert added_lead.assigned_user_id == user_id
    assert added_lead.status == "new"
    resolve_mock.assert_called_once()


@pytest.mark.asyncio
async def test_sync_lead_creates_new_lead_with_none_when_unresolved(monkeypatch) -> None:
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.add = MagicMock()
    monkeypatch.setattr(
        contacts_repository, "resolve_new_lead_assigned_user_id", AsyncMock(return_value=None)
    )
    repo = ContactRepository(session)

    await repo.sync_lead(
        tenant_id=uuid4(),
        phone_hash=PHONE_HASH,
        classification="new_contact",
        source="kcell",
        occurred_at=EARLIER,
        external_user="999",
    )

    added_lead = session.add.call_args.args[0]
    assert added_lead.assigned_user_id is None


@pytest.mark.asyncio
async def test_sync_lead_never_overwrites_an_existing_assignment(monkeypatch) -> None:
    tenant_id = uuid4()
    existing_owner = uuid4()
    existing_lead = _lead(tenant_id=tenant_id, assigned_user_id=existing_owner, last_contact_at=EARLIER)
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=existing_lead)
    resolve_mock = AsyncMock(return_value=uuid4())  # a different resolution this time
    monkeypatch.setattr(contacts_repository, "resolve_new_lead_assigned_user_id", resolve_mock)
    repo = ContactRepository(session)

    await repo.sync_lead(
        tenant_id=tenant_id,
        phone_hash=PHONE_HASH,
        classification="repeat_contact",
        source="kcell",
        occurred_at=LATER,
        external_user="202",
    )

    assert existing_lead.assigned_user_id == existing_owner  # unchanged
    resolve_mock.assert_not_called()  # never even attempts resolution when already assigned


@pytest.mark.asyncio
async def test_sync_lead_fills_in_a_missing_assignment_on_an_existing_lead(monkeypatch) -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    existing_lead = _lead(
        tenant_id=tenant_id, source="whatsapp", assigned_user_id=None, last_contact_at=EARLIER
    )
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=existing_lead)
    monkeypatch.setattr(
        contacts_repository, "resolve_new_lead_assigned_user_id", AsyncMock(return_value=user_id)
    )
    repo = ContactRepository(session)

    await repo.sync_lead(
        tenant_id=tenant_id,
        phone_hash=PHONE_HASH,
        classification="repeat_contact",
        source="whatsapp",
        occurred_at=LATER,
    )

    assert existing_lead.assigned_user_id == user_id
    assert existing_lead.last_contact_at == LATER


@pytest.mark.asyncio
async def test_sync_lead_never_touches_a_won_lead(monkeypatch) -> None:
    tenant_id = uuid4()
    won_lead = _lead(
        tenant_id=tenant_id,
        branch_id=uuid4(),
        patient_id=uuid4(),
        assigned_user_id=None,
        status="won",
        last_contact_at=EARLIER,
    )
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=won_lead)
    resolve_mock = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(contacts_repository, "resolve_new_lead_assigned_user_id", resolve_mock)
    repo = ContactRepository(session)

    await repo.sync_lead(
        tenant_id=tenant_id,
        phone_hash=PHONE_HASH,
        classification="repeat_contact",
        source="kcell",
        occurred_at=LATER,
        external_user="101",
    )

    assert won_lead.status == "won"
    assert won_lead.assigned_user_id is None  # not retroactively filled in either
    assert won_lead.last_contact_at == EARLIER  # untouched entirely
    resolve_mock.assert_not_called()


@pytest.mark.asyncio
async def test_sync_lead_is_idempotent_across_a_retried_webhook(monkeypatch) -> None:
    """Simulates sync_lead being reached twice for the same contact (the
    upstream Call.external_id / WhatsAppMessage.external_message_id
    de-dup is what normally prevents this at the router level, but
    sync_lead must be safe on its own merits too)."""
    tenant_id = uuid4()
    user_id = uuid4()
    lead_state = _lead(tenant_id=tenant_id, assigned_user_id=None, last_contact_at=EARLIER)
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=lead_state)
    resolve_mock = AsyncMock(return_value=user_id)
    monkeypatch.setattr(contacts_repository, "resolve_new_lead_assigned_user_id", resolve_mock)
    repo = ContactRepository(session)

    for _ in range(2):
        await repo.sync_lead(
            tenant_id=tenant_id,
            phone_hash=PHONE_HASH,
            classification="repeat_contact",
            source="kcell",
            occurred_at=LATER,
            external_user="101",
        )

    assert lead_state.assigned_user_id == user_id
    resolve_mock.assert_called_once()  # second call sees assigned_user_id already set, skips it


@pytest.mark.asyncio
async def test_sync_lead_skips_existing_1c_patients_without_any_lead_or_resolution_work(monkeypatch) -> None:
    session = AsyncMock()
    resolve_mock = AsyncMock()
    monkeypatch.setattr(contacts_repository, "resolve_new_lead_assigned_user_id", resolve_mock)
    repo = ContactRepository(session)

    await repo.sync_lead(
        tenant_id=uuid4(),
        phone_hash=PHONE_HASH,
        classification="existing_1c_patient",
        source="kcell",
        occurred_at=EARLIER,
        external_user="101",
    )

    session.scalar.assert_not_called()
    resolve_mock.assert_not_called()
