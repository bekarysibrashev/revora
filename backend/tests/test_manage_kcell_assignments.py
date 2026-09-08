from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.cli import manage_kcell_assignments
from app.modules.auth.models import User, UserRole


def _mock_set_tenant_context(monkeypatch) -> AsyncMock:
    """set_tenant_context is mocked in every test below -- these tests are
    about the CLI's own decisions (which user gets picked, what gets
    printed, whether execute is called), not about re-verifying that
    AuthRepository issues the right set_config() call (that's covered by
    auth/repository's own tests and by test_backfill_leads.py)."""
    mocked = AsyncMock()
    monkeypatch.setattr("app.cli.manage_kcell_assignments.AuthRepository.set_tenant_context", mocked)
    return mocked


# ---------------------------------------------------------------------------
# _resolve_tenant_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_tenant_id_raises_for_unknown_or_inactive_slug(monkeypatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(
        "app.cli.manage_kcell_assignments.AuthRepository.get_tenant_by_slug", AsyncMock(return_value=None)
    )

    with pytest.raises(SystemExit):
        await manage_kcell_assignments._resolve_tenant_id(session, "does-not-exist")


# ---------------------------------------------------------------------------
# cmd_set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_set_assigns_an_existing_user_in_the_same_tenant(monkeypatch, capsys) -> None:
    tenant_id = uuid4()
    user = User(
        id=uuid4(),
        tenant_id=tenant_id,
        email="doctor@example.com",
        full_name="Doctor",
        password_hash="x",
        role=UserRole.MANAGER,
        is_active=True,
    )

    _mock_set_tenant_context(monkeypatch)
    monkeypatch.setattr(
        "app.cli.manage_kcell_assignments.AuthRepository.get_user_by_email", AsyncMock(return_value=user)
    )

    session = AsyncMock()
    session.execute = AsyncMock()

    await manage_kcell_assignments.cmd_set(session, tenant_id, "101", "Doctor@Example.com")

    session.execute.assert_called_once()
    statement = session.execute.call_args.args[0]
    assert statement.table.name == "kcell_extension_assignments"
    assert "101 -> doctor@example.com" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cmd_set_rejects_a_user_not_found_in_this_tenant(monkeypatch) -> None:
    """get_user_by_email is always scoped to the resolved tenant_id, so a
    user that exists but belongs to a different tenant looks identical to
    no user at all -- cmd_set must refuse rather than fall back to a
    cross-tenant match of any kind."""
    tenant_id = uuid4()

    _mock_set_tenant_context(monkeypatch)
    monkeypatch.setattr(
        "app.cli.manage_kcell_assignments.AuthRepository.get_user_by_email", AsyncMock(return_value=None)
    )

    session = AsyncMock()
    session.execute = AsyncMock()

    with pytest.raises(SystemExit):
        await manage_kcell_assignments.cmd_set(session, tenant_id, "101", "someone@other-tenant.example")

    session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# cmd_mark_ambiguous
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_mark_ambiguous_writes_a_null_assigned_user_id(monkeypatch, capsys) -> None:
    tenant_id = uuid4()

    _mock_set_tenant_context(monkeypatch)
    session = AsyncMock()
    session.execute = AsyncMock()

    await manage_kcell_assignments.cmd_mark_ambiguous(session, tenant_id, "front-desk")

    session.execute.assert_called_once()
    statement = session.execute.call_args.args[0]
    assert statement.table.name == "kcell_extension_assignments"
    assert "front-desk marked ambiguous" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# cmd_delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_delete_reports_deleted_when_a_mapping_existed(monkeypatch, capsys) -> None:
    tenant_id = uuid4()

    _mock_set_tenant_context(monkeypatch)
    result = MagicMock()
    result.rowcount = 1
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    await manage_kcell_assignments.cmd_delete(session, tenant_id, "101")

    assert "Deleted mapping for 101" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cmd_delete_reports_nothing_to_delete_when_no_mapping_existed(monkeypatch, capsys) -> None:
    tenant_id = uuid4()

    _mock_set_tenant_context(monkeypatch)
    result = MagicMock()
    result.rowcount = 0
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    await manage_kcell_assignments.cmd_delete(session, tenant_id, "999")

    assert "No mapping existed for 999" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# cmd_list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_list_shows_configured_owners_ambiguous_marks_and_unconfigured_extensions(
    monkeypatch, capsys
) -> None:
    tenant_id = uuid4()
    user_id = uuid4()

    configured_result = MagicMock()
    configured_result.all.return_value = [("101", user_id), ("front-desk", None)]

    emails_result = MagicMock()
    emails_result.all.return_value = [(user_id, "doctor@example.com")]

    seen_result = MagicMock()
    seen_result.scalars.return_value.all.return_value = ["101", "front-desk", "202"]

    _mock_set_tenant_context(monkeypatch)
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[configured_result, emails_result, seen_result])

    await manage_kcell_assignments.cmd_list(session, tenant_id)

    out = capsys.readouterr().out
    assert "101: doctor@example.com" in out
    assert "front-desk: ambiguous" in out

    # "202" was seen in calls but never configured -- must show up as
    # unconfigured. "101" and "front-desk" are already configured, so they
    # must NOT be re-listed as unconfigured, even though they were also
    # returned by the (mocked) distinct Call.external_user query.
    unconfigured_section = out.split("Seen in calls but not yet configured")[1]
    assert "202" in unconfigured_section
    assert "101" not in unconfigured_section
    assert "front-desk" not in unconfigured_section


@pytest.mark.asyncio
async def test_cmd_list_never_prints_a_phone_number(monkeypatch, capsys) -> None:
    """Guards the "never displays PII" requirement: only extension
    identifiers and emails are ever printed -- specifically, nothing that
    looks like a phone_hash (a 64-char hex string, same shape
    backfill_leads.py never logs either) ever reaches stdout."""
    tenant_id = uuid4()

    configured_result = MagicMock()
    configured_result.all.return_value = []
    seen_result = MagicMock()
    seen_result.scalars.return_value.all.return_value = ["101"]

    _mock_set_tenant_context(monkeypatch)
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[configured_result, seen_result])

    await manage_kcell_assignments.cmd_list(session, tenant_id)

    out = capsys.readouterr().out
    phone_hash_shaped = "a" * 64
    assert phone_hash_shaped not in out
    assert "+7" not in out and "+1" not in out  # no phone-number-looking prefix
