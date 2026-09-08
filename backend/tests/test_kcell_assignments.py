"""Administering Kcell extension assignments from the Revora UI.

Until now this mapping could only be configured through
app.cli.manage_kcell_assignments, which needs a shell on the server. The
clinic's Render plan has none, so in practice it was never configured --
and an unconfigured extension silently produces leads with no responsible
employee. These tests pin the rules that make an HTTP surface safe enough
to replace the CLI: who may use it, what it refuses to guess, and what it
records.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.kcell.repository import KcellAssignmentsRepository
from app.modules.kcell.service import (
    AMBIGUOUS,
    ASSIGNED,
    UNRESOLVED,
    KcellAssignmentsService,
)


def make_user(role: UserRole = UserRole.OWNER, tenant_id: UUID | None = None) -> User:
    user = User(
        id=uuid4(),
        tenant_id=tenant_id or uuid4(),
        email=f"{role.value}@example.test",
        full_name="Admin User",
        password_hash="unused",
        role=role,
        is_active=True,
    )
    user.branch_links = []
    return user


@dataclass
class FakeAssignment:
    external_user: str
    assigned_user_id: UUID | None
    updated_at: datetime | None = None


@dataclass
class FakeAudit:
    external_user: str
    action: str
    previous_assigned_user_id: UUID | None
    new_assigned_user_id: UUID | None
    changed_by_user_id: UUID | None
    details: dict | None
    created_at: datetime


@dataclass
class FakeRepository:
    """Stands in for KcellAssignmentsRepository. Every method takes a
    tenant_id, and the fake only ever answers for `tenant_id`, so a service
    that forgot to scope a call would read nothing rather than another
    clinic's data."""

    tenant_id: UUID
    rows: dict[str, FakeAssignment] = field(default_factory=dict)
    calls: dict[str, int] = field(default_factory=dict)
    leads: dict[str, tuple[int, int]] = field(default_factory=dict)
    users: dict[UUID, User] = field(default_factory=dict)
    resolvable: dict[UUID, UUID] = field(default_factory=dict)
    ambiguous: int = 0
    ownerless: int = 0
    audits: list[FakeAudit] = field(default_factory=list)
    applied: dict[UUID, UUID] | None = None

    def _check(self, tenant_id: UUID) -> bool:
        return tenant_id == self.tenant_id

    async def configured(self, tenant_id):
        if not self._check(tenant_id):
            return []
        return sorted(self.rows.values(), key=lambda row: row.external_user)

    async def extensions_seen_in_calls(self, tenant_id):
        return dict(self.calls) if self._check(tenant_id) else {}

    async def lead_counts_by_extension(self, tenant_id):
        return dict(self.leads) if self._check(tenant_id) else {}

    async def users_by_id(self, tenant_id, ids):
        if not self._check(tenant_id):
            return {}
        return {key: value for key, value in self.users.items() if key in ids}

    async def get_user(self, tenant_id, user_id):
        if not self._check(tenant_id):
            return None
        return self.users.get(user_id)

    async def get(self, tenant_id, external_user):
        return self.rows.get(external_user) if self._check(tenant_id) else None

    async def upsert(self, tenant_id, external_user, assigned_user_id):
        existing = self.rows.get(external_user)
        previous = existing.assigned_user_id if existing else None
        self.rows[external_user] = FakeAssignment(external_user, assigned_user_id)
        return self.rows[external_user], previous

    async def remove(self, tenant_id, external_user):
        return self.rows.pop(external_user, None) is not None

    async def record_audit(self, **kwargs):
        self.audits.append(
            FakeAudit(
                external_user=kwargs["external_user"],
                action=kwargs["action"],
                previous_assigned_user_id=kwargs["previous_assigned_user_id"],
                new_assigned_user_id=kwargs["new_assigned_user_id"],
                changed_by_user_id=kwargs["changed_by_user_id"],
                details=kwargs.get("details"),
                created_at=datetime.now(UTC),
            )
        )

    async def audit_trail(self, tenant_id, limit=100):
        return list(reversed(self.audits))[:limit] if self._check(tenant_id) else []

    async def resolve_backfill_candidates(self, tenant_id):
        if not self._check(tenant_id):
            return {}, 0
        return dict(self.resolvable), self.ambiguous

    async def count_ownerless_leads(self, tenant_id):
        return self.ownerless if self._check(tenant_id) else 0

    async def apply_backfill(self, tenant_id, resolvable):
        self.applied = dict(resolvable)
        return len(resolvable)

    @staticmethod
    def now():
        return datetime.now(UTC)


def build(role: UserRole = UserRole.OWNER, **kwargs):
    user = make_user(role)
    repository = FakeRepository(tenant_id=user.tenant_id, **kwargs)
    return user, repository, KcellAssignmentsService(repository)


# --- access control ------------------------------------------------------


@pytest.mark.parametrize(
    "role", [UserRole.SALES_MANAGER, UserRole.ADMINISTRATOR]
)
@pytest.mark.asyncio
async def test_only_owners_and_managers_may_read_the_mapping(role) -> None:
    """Assignment decides who is credited with revenue, so it is not an
    ordinary settings screen."""
    user, _repository, service = build(role)

    with pytest.raises(AppError) as error:
        await service.list_assignments(user)

    assert error.value.status_code == 403


@pytest.mark.parametrize("role", [UserRole.SALES_MANAGER, UserRole.ADMINISTRATOR])
@pytest.mark.asyncio
async def test_only_owners_and_managers_may_run_the_backfill(role) -> None:
    user, _repository, service = build(role)

    with pytest.raises(AppError) as error:
        await service.run_backfill(user)

    assert error.value.status_code == 403


# --- listing -------------------------------------------------------------


@pytest.mark.asyncio
async def test_listing_separates_assigned_ambiguous_and_never_configured() -> None:
    """"Never configured" is a to-do item; "ambiguous" is a decision
    someone already made. Collapsing them would hide the work."""
    owner = make_user(UserRole.MANAGER)
    employee = make_user()
    employee.tenant_id = owner.tenant_id
    repository = FakeRepository(
        tenant_id=owner.tenant_id,
        rows={
            "101": FakeAssignment("101", employee.id),
            "200": FakeAssignment("200", None),
        },
        calls={"101": 40, "200": 12, "999": 7},
        leads={"101": (10, 2), "200": (5, 5), "999": (3, 3)},
        users={employee.id: employee},
    )
    service = KcellAssignmentsService(repository)

    response = await service.list_assignments(owner)

    by_extension = {item.external_user: item for item in response.items}
    assert by_extension["101"].status == ASSIGNED
    assert by_extension["101"].assigned_user_email == employee.email
    assert by_extension["200"].status == AMBIGUOUS
    assert by_extension["999"].status == UNRESOLVED
    assert response.unresolved == 1
    assert response.configured == 2


@pytest.mark.asyncio
async def test_listing_shows_how_much_history_each_extension_accounts_for() -> None:
    owner = make_user()
    repository = FakeRepository(
        tenant_id=owner.tenant_id,
        calls={"777": 31},
        leads={"777": (9, 4)},
    )
    service = KcellAssignmentsService(repository)

    response = await service.list_assignments(owner)

    item = response.items[0]
    assert (item.calls_total, item.leads_total, item.leads_without_owner) == (31, 9, 4)


@pytest.mark.asyncio
async def test_listing_never_exposes_a_phone_number_or_phone_hash() -> None:
    owner = make_user()
    repository = FakeRepository(
        tenant_id=owner.tenant_id, calls={"101": 3}, leads={"101": (1, 1)}
    )
    service = KcellAssignmentsService(repository)

    response = await service.list_assignments(owner)

    rendered = response.model_dump_json()
    assert "phone" not in rendered.casefold()
    assert "hash" not in rendered.casefold()


# --- setting an owner ----------------------------------------------------


@pytest.mark.asyncio
async def test_setting_an_owner_records_who_changed_it() -> None:
    owner = make_user()
    employee = make_user()
    repository = FakeRepository(
        tenant_id=owner.tenant_id, users={employee.id: employee}
    )
    service = KcellAssignmentsService(repository)

    item = await service.set_assignment(owner, "101", employee.id)

    assert item.status == ASSIGNED
    assert item.assigned_user_id == employee.id
    entry = repository.audits[-1]
    assert (entry.action, entry.external_user) == ("set", "101")
    assert entry.changed_by_user_id == owner.id
    assert entry.previous_assigned_user_id is None
    assert entry.new_assigned_user_id == employee.id


@pytest.mark.asyncio
async def test_reassigning_records_the_previous_owner() -> None:
    owner = make_user()
    first, second = make_user(), make_user()
    repository = FakeRepository(
        tenant_id=owner.tenant_id,
        rows={"101": FakeAssignment("101", first.id)},
        users={first.id: first, second.id: second},
    )
    service = KcellAssignmentsService(repository)

    await service.set_assignment(owner, "101", second.id)

    entry = repository.audits[-1]
    assert entry.previous_assigned_user_id == first.id
    assert entry.new_assigned_user_id == second.id


@pytest.mark.asyncio
async def test_an_employee_from_another_clinic_is_reported_as_not_found() -> None:
    """404 rather than 403 on purpose: this endpoint must not confirm that
    a user id exists in some other tenant."""
    owner = make_user()
    repository = FakeRepository(tenant_id=owner.tenant_id, users={})
    service = KcellAssignmentsService(repository)

    with pytest.raises(AppError) as error:
        await service.set_assignment(owner, "101", uuid4())

    assert error.value.status_code == 404
    assert repository.audits == []


@pytest.mark.asyncio
async def test_a_deactivated_employee_cannot_own_an_extension() -> None:
    owner = make_user()
    employee = make_user()
    employee.is_active = False
    repository = FakeRepository(
        tenant_id=owner.tenant_id, users={employee.id: employee}
    )
    service = KcellAssignmentsService(repository)

    with pytest.raises(AppError) as error:
        await service.set_assignment(owner, "101", employee.id)

    assert error.value.status_code == 422


@pytest.mark.parametrize("value", ["", "   "])
@pytest.mark.asyncio
async def test_an_empty_extension_is_rejected(value: str) -> None:
    owner = make_user()
    employee = make_user()
    repository = FakeRepository(
        tenant_id=owner.tenant_id, users={employee.id: employee}
    )
    service = KcellAssignmentsService(repository)

    with pytest.raises(AppError) as error:
        await service.set_assignment(owner, value, employee.id)

    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_surrounding_whitespace_never_creates_a_second_extension() -> None:
    owner = make_user()
    employee = make_user()
    repository = FakeRepository(
        tenant_id=owner.tenant_id, users={employee.id: employee}
    )
    service = KcellAssignmentsService(repository)

    await service.set_assignment(owner, "101", employee.id)
    await service.set_assignment(owner, "  101  ", employee.id)

    assert list(repository.rows) == ["101"]


# --- ambiguous and delete ------------------------------------------------


@pytest.mark.asyncio
async def test_marking_ambiguous_is_recorded_as_a_deliberate_decision() -> None:
    owner = make_user()
    employee = make_user()
    repository = FakeRepository(
        tenant_id=owner.tenant_id,
        rows={"200": FakeAssignment("200", employee.id)},
        users={employee.id: employee},
    )
    service = KcellAssignmentsService(repository)

    item = await service.mark_ambiguous(owner, "200")

    assert item.status == AMBIGUOUS
    assert item.assigned_user_id is None
    entry = repository.audits[-1]
    assert entry.action == "mark_ambiguous"
    assert entry.previous_assigned_user_id == employee.id


@pytest.mark.asyncio
async def test_deleting_an_unconfigured_extension_is_a_404_not_a_silent_success() -> None:
    owner = make_user()
    repository = FakeRepository(tenant_id=owner.tenant_id)
    service = KcellAssignmentsService(repository)

    with pytest.raises(AppError) as error:
        await service.delete_assignment(owner, "404")

    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_deleting_records_what_the_mapping_used_to_be() -> None:
    owner = make_user()
    employee = make_user()
    repository = FakeRepository(
        tenant_id=owner.tenant_id,
        rows={"101": FakeAssignment("101", employee.id)},
        users={employee.id: employee},
    )
    service = KcellAssignmentsService(repository)

    await service.delete_assignment(owner, "101")

    assert "101" not in repository.rows
    entry = repository.audits[-1]
    assert entry.action == "delete"
    assert entry.previous_assigned_user_id == employee.id


# --- backfill ------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_reports_the_blast_radius_without_changing_anything() -> None:
    owner = make_user()
    employee = make_user()
    repository = FakeRepository(
        tenant_id=owner.tenant_id,
        rows={"101": FakeAssignment("101", employee.id)},
        calls={"101": 20, "999": 4},
        resolvable={uuid4(): employee.id, uuid4(): employee.id},
        ambiguous=3,
        ownerless=10,
    )
    service = KcellAssignmentsService(repository)

    preview = await service.preview_backfill(owner)

    assert preview.leads_without_owner == 10
    assert preview.leads_resolvable == 2
    assert preview.leads_ambiguous == 3
    assert preview.extensions_unresolved == 1
    assert repository.applied is None  # nothing was written
    assert repository.audits == []


@pytest.mark.asyncio
async def test_backfill_applies_only_the_unambiguous_leads_and_is_audited() -> None:
    owner = make_user()
    employee = make_user()
    lead_one, lead_two = uuid4(), uuid4()
    repository = FakeRepository(
        tenant_id=owner.tenant_id,
        rows={"101": FakeAssignment("101", employee.id)},
        resolvable={lead_one: employee.id, lead_two: employee.id},
        ambiguous=4,
        ownerless=10,
    )
    service = KcellAssignmentsService(repository)

    result = await service.run_backfill(owner)

    assert result.leads_updated == 2
    assert result.leads_ambiguous == 4
    assert result.leads_untouched == 8
    assert repository.applied == {lead_one: employee.id, lead_two: employee.id}
    entry = repository.audits[-1]
    assert entry.action == "backfill"
    assert entry.details == {
        "leads_updated": 2,
        "leads_ambiguous": 4,
        "leads_without_owner_before": 10,
    }


@pytest.mark.asyncio
async def test_a_backfill_with_nothing_to_do_is_still_recorded() -> None:
    """An audit entry showing zero changes is the evidence that someone
    pressed the button and nothing happened -- otherwise a no-op looks
    identical to a run that never happened."""
    owner = make_user()
    repository = FakeRepository(tenant_id=owner.tenant_id, ownerless=0)
    service = KcellAssignmentsService(repository)

    result = await service.run_backfill(owner)

    assert result.leads_updated == 0
    assert repository.audits[-1].action == "backfill"


@pytest.mark.asyncio
async def test_audit_trail_names_the_person_who_made_each_change() -> None:
    owner = make_user()
    employee = make_user()
    repository = FakeRepository(
        tenant_id=owner.tenant_id, users={owner.id: owner, employee.id: employee}
    )
    service = KcellAssignmentsService(repository)
    await service.set_assignment(owner, "101", employee.id)

    trail = await service.audit_trail(owner)

    assert trail.total == 1
    assert trail.items[0].changed_by_email == owner.email
    assert trail.items[0].action == "set"


# --- the resolution rule itself ------------------------------------------


@pytest.mark.asyncio
async def test_a_lead_reached_by_two_owners_is_never_guessed_at() -> None:
    """The whole point of the mapping is that attribution is explicit. A
    lead whose calls came from extensions belonging to two different
    employees is counted as ambiguous and left alone."""
    session = AsyncMock()
    lead_one, lead_two = uuid4(), uuid4()
    owner_a, owner_b = uuid4(), uuid4()
    # await session.execute(...) resolves to this MagicMock, whose .all()
    # must be synchronous like the real Result's.
    session.execute.return_value = MagicMock()
    session.execute.return_value.all.return_value = [
        (lead_one, owner_a),
        (lead_one, owner_b),  # two different owners -> ambiguous
        (lead_two, owner_a),
        (lead_two, owner_a),  # same owner twice -> still resolvable
    ]
    repository = KcellAssignmentsRepository(session)

    resolvable, ambiguous = await repository.resolve_backfill_candidates(uuid4())

    assert resolvable == {lead_two: owner_a}
    assert ambiguous == 1


@pytest.mark.asyncio
async def test_backfill_candidates_exclude_won_leads_and_owned_leads() -> None:
    """A won lead is already a patient, and a lead that gained an owner
    between preview and apply must keep it. Both exclusions live in SQL, so
    they are checked by compiling the statement."""
    repository = KcellAssignmentsRepository(AsyncMock())

    compiled = str(
        repository._ownerless_lead_candidates(uuid4()).compile(
            compile_kwargs={"literal_binds": False}
        )
    )

    assert "leads.assigned_user_id IS NULL" in compiled
    assert "leads.status !=" in compiled
    assert "leads.tenant_id" in compiled
    assert "kcell_extension_assignments.assigned_user_id IS NOT NULL" in compiled


@pytest.mark.asyncio
async def test_backfill_re_checks_each_lead_before_writing() -> None:
    """apply_backfill re-reads the leads inside the transaction, so a live
    webhook that assigned an owner in the meantime wins over a stale plan.
    """
    session = AsyncMock()
    already_owned = type(
        "Lead", (), {"id": uuid4(), "assigned_user_id": uuid4(), "status": "new"}
    )()
    still_free = type(
        "Lead", (), {"id": uuid4(), "assigned_user_id": None, "status": "new"}
    )()
    won = type(
        "Lead", (), {"id": uuid4(), "assigned_user_id": None, "status": "won"}
    )()
    session.scalars.return_value = MagicMock()
    session.scalars.return_value.all.return_value = [already_owned, still_free, won]
    repository = KcellAssignmentsRepository(session)
    new_owner = uuid4()

    updated = await repository.apply_backfill(
        uuid4(),
        {
            already_owned.id: new_owner,
            still_free.id: new_owner,
            won.id: new_owner,
        },
    )

    assert updated == 1
    assert still_free.assigned_user_id == new_owner
    assert already_owned.assigned_user_id != new_owner
    assert won.assigned_user_id is None
