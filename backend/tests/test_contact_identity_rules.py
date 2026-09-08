"""Two invariants of the "new inquiry" definition that ordinary unit tests
miss, because both live in SQL rather than in branching Python.

1. A phone number that has EVER belonged to a 1C patient is not a new
   inquiry, even if that patient card is now inactive, deleted or merged
   away. app.cli.backfill_leads already applied this historical rule to
   old contacts (see its module docstring: "active OR inactive -- 1C
   marking a card deleted does not un-know the number"), while the live
   path filtered on Patient.is_active and disagreed with it. These tests
   pin the two together so they cannot drift apart again.

2. Exactly one code path may construct a Lead from live traffic. A second
   one racing it under autoflush=False is not a style problem: neither
   call's select(Lead) sees the other's unflushed INSERT, so both insert
   the same (tenant_id, external_id) and the whole webhook dies on the
   next flush. That has already happened once here.
"""

import ast
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import app
from app.modules.contacts.repository import ContactRepository

# app is a namespace package (no __init__.py), so __file__ is None and the
# package root has to come from __path__ instead.
APP_ROOT = Path(next(iter(app.__path__))).resolve()

PHONE_HASH = "b" * 64


def _compiled(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": False}))


async def _capture_is_patient_statement(*, found: bool):
    session = AsyncMock()
    session.scalar.return_value = uuid4() if found else None
    repository = ContactRepository(session)
    tenant_id = uuid4()
    result = await repository.is_patient(tenant_id, {PHONE_HASH})
    return result, _compiled(session.scalar.call_args.args[0])


@pytest.mark.asyncio
async def test_is_patient_does_not_filter_on_is_active() -> None:
    """The regression this whole file exists for: a number the clinic has
    known since 2019 must not be re-classified as a fresh marketing lead
    just because someone archived the card in 1C."""
    _, compiled = await _capture_is_patient_statement(found=True)

    assert "is_active" not in compiled


@pytest.mark.asyncio
async def test_is_patient_is_true_for_a_historically_known_number() -> None:
    found, _ = await _capture_is_patient_statement(found=True)

    assert found is True


@pytest.mark.asyncio
async def test_is_patient_is_false_for_a_number_1c_has_never_seen() -> None:
    found, _ = await _capture_is_patient_statement(found=False)

    assert found is False


@pytest.mark.asyncio
async def test_is_patient_stays_scoped_to_one_tenant() -> None:
    """Dropping is_active must not accidentally widen the lookup: another
    clinic's patient list can never decide whether this clinic's caller is
    a new inquiry. FORCE ROW LEVEL SECURITY is the second layer; this
    predicate is the first."""
    _, compiled = await _capture_is_patient_statement(found=True)

    assert "patients.tenant_id" in compiled
    assert "patients.phone_hash" in compiled


def test_new_contact_reporting_filters_do_not_use_is_active() -> None:
    """Classification (is_patient) and the reports built from it must
    agree on the same definition. If the reports still filtered on
    is_active, an archived patient would be excluded from "Новые
    обращения" at intake but counted in the summary totals."""
    repository = ContactRepository(AsyncMock())
    tenant_id = uuid4()
    from datetime import date

    filters = repository._new_contact_filters(
        tenant_id, date(2026, 8, 1), date(2026, 8, 31)
    )

    rendered = " ".join(_compiled(item) for item in filters)
    assert "is_active" not in rendered


ALLOWED_LEAD_CONSTRUCTORS = frozenset(
    {
        # The single live path: ContactRegistry.register_inbound ->
        # ContactRepository.sync_lead, reached from both the Kcell and the
        # WhatsApp webhook.
        "app/modules/contacts/repository.py",
        # Demo/seed data only, never imported by a running service.
        "app/cli/seed_demo_data.py",
    }
)


def test_only_one_live_path_constructs_a_lead() -> None:
    """app.cli.backfill_leads is deliberately absent from the allow-list:
    it writes historical leads with INSERT ... ON CONFLICT DO NOTHING
    (pg_insert), never by constructing an ORM Lead, so it cannot collide
    with a pending unflushed insert the way a second ORM path would.
    """
    root = APP_ROOT
    offenders: list[str] = []

    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Lead"
            ):
                relative = path.relative_to(root.parent).as_posix()
                if relative not in ALLOWED_LEAD_CONSTRUCTORS:
                    offenders.append(f"{relative}:{node.lineno}")

    assert offenders == [], (
        "A second live path is constructing sales.Lead rows: "
        f"{offenders}. Under autoflush=False two such paths handling the "
        "same inbound both miss each other's pending INSERT and violate "
        "leads(tenant_id, external_id) on the next flush. Route the new "
        "caller through ContactRepository.sync_lead instead."
    )
