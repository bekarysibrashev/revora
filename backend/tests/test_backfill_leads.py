from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.cli import backfill_leads
from app.cli.backfill_leads import (
    ContactAggregate,
    PatientMatch,
    merge_contact_events,
    resolve_assignment,
    resolve_lead_outcome,
)


# ---------------------------------------------------------------------------
# merge_contact_events
# ---------------------------------------------------------------------------


def test_merge_keeps_earliest_source_and_latest_contact() -> None:
    phone_hash = "a" * 64
    other_hash = "b" * 64
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    events = [
        (phone_hash, "whatsapp", t0 + timedelta(hours=5), None),
        (phone_hash, "kcell", t0, "101"),  # earlier -- becomes the first_source
        (phone_hash, "whatsapp", t0 + timedelta(days=2), None),  # later -- becomes last_at
        (other_hash, "whatsapp", t0, None),
    ]

    merged = merge_contact_events(events)

    assert set(merged) == {phone_hash, other_hash}
    assert merged[phone_hash].first_source == "kcell"
    assert merged[phone_hash].first_at == t0
    assert merged[phone_hash].last_at == t0 + timedelta(days=2)
    assert merged[phone_hash].first_external_user == "101"


def test_merge_single_event_is_its_own_first_and_last() -> None:
    phone_hash = "c" * 64
    occurred_at = datetime(2026, 5, 1, 9, tzinfo=UTC)

    merged = merge_contact_events([(phone_hash, "kcell", occurred_at, "202")])

    assert merged[phone_hash].first_at == occurred_at
    assert merged[phone_hash].last_at == occurred_at
    assert merged[phone_hash].first_source == "kcell"
    assert merged[phone_hash].first_external_user == "202"


def test_merge_simultaneous_kcell_and_whatsapp_is_one_lead_sourced_from_the_first() -> None:
    """Kcell and WhatsApp both touching the same number must still collapse
    to a single aggregate, with the *earlier* channel winning as the
    source -- never two Leads for one phone_hash."""
    phone_hash = "d" * 64
    t0 = datetime(2026, 3, 1, tzinfo=UTC)
    events = [
        (phone_hash, "whatsapp", t0 + timedelta(minutes=1), None),
        (phone_hash, "kcell", t0, "303"),
    ]

    merged = merge_contact_events(events)

    assert len(merged) == 1
    assert merged[phone_hash].first_source == "kcell"
    assert merged[phone_hash].first_external_user == "303"


def test_merge_later_whatsapp_does_not_clear_the_kcell_first_external_user() -> None:
    phone_hash = "e" * 64
    t0 = datetime(2026, 3, 1, tzinfo=UTC)
    merged = merge_contact_events(
        [
            (phone_hash, "kcell", t0, "404"),
            (phone_hash, "whatsapp", t0 + timedelta(days=1), None),
        ]
    )
    assert merged[phone_hash].first_source == "kcell"
    assert merged[phone_hash].first_external_user == "404"
    assert merged[phone_hash].last_at == t0 + timedelta(days=1)


# ---------------------------------------------------------------------------
# resolve_lead_outcome
# ---------------------------------------------------------------------------


def test_patient_existed_before_the_contact_creates_no_lead() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    first_contact_at = now - timedelta(days=5)
    match = PatientMatch(
        patient_id=uuid4(), branch_id=uuid4(), first_visit_at=first_contact_at - timedelta(days=200)
    )

    outcome = resolve_lead_outcome(
        patient_matches=[match],
        first_contact_at=first_contact_at,
        last_contact_at=first_contact_at,
        now=now,
    )

    assert outcome is None


def test_contact_before_first_visit_wins_and_copies_real_branch() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    first_contact_at = now - timedelta(days=30)
    patient_id = uuid4()
    branch_id = uuid4()
    match = PatientMatch(
        patient_id=patient_id, branch_id=branch_id, first_visit_at=first_contact_at + timedelta(days=2)
    )

    outcome = resolve_lead_outcome(
        patient_matches=[match],
        first_contact_at=first_contact_at,
        last_contact_at=now - timedelta(days=400),  # ancient last touch, irrelevant once won
        now=now,
    )

    assert outcome == ("won", patient_id, branch_id)


def test_contact_at_the_same_instant_as_first_visit_wins() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    contact_at = now - timedelta(days=10)
    patient_id = uuid4()
    match = PatientMatch(patient_id=patient_id, branch_id=None, first_visit_at=contact_at)

    outcome = resolve_lead_outcome(
        patient_matches=[match], first_contact_at=contact_at, last_contact_at=contact_at, now=now
    )

    assert outcome == ("won", patient_id, None)


def test_no_patient_match_and_recent_contact_is_new() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)

    outcome = resolve_lead_outcome(
        patient_matches=[],
        first_contact_at=now - timedelta(days=1),
        last_contact_at=now - timedelta(days=1),
        now=now,
    )

    assert outcome == ("new", None, None)


def test_no_patient_match_and_stale_contact_is_lost() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)

    outcome = resolve_lead_outcome(
        patient_matches=[],
        first_contact_at=now - timedelta(days=30),
        last_contact_at=now - timedelta(days=30),
        now=now,
    )

    assert outcome == ("lost", None, None)


def test_lost_boundary_is_exactly_lost_lead_days() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)

    just_inside = resolve_lead_outcome(
        patient_matches=[],
        first_contact_at=now - timedelta(days=14) + timedelta(seconds=1),
        last_contact_at=now - timedelta(days=14) + timedelta(seconds=1),
        now=now,
    )
    exactly_at = resolve_lead_outcome(
        patient_matches=[],
        first_contact_at=now - timedelta(days=14),
        last_contact_at=now - timedelta(days=14),
        now=now,
    )

    assert just_inside[0] == "new"
    assert exactly_at[0] == "lost"


def test_inactive_old_patient_match_does_not_become_a_new_lead() -> None:
    """An inactive Patient row (is_active is not even part of PatientMatch --
    the caller must fetch it regardless of the flag) whose first_visit_at
    predates the contact must still resolve to "no Lead", exactly like an
    active one -- never fall through to "new"/"lost" just because the
    patient happens to be inactive today."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    first_contact_at = now - timedelta(days=2)  # a fresh-looking contact
    old_inactive_match = PatientMatch(
        patient_id=uuid4(), branch_id=uuid4(), first_visit_at=now - timedelta(days=900)
    )

    outcome = resolve_lead_outcome(
        patient_matches=[old_inactive_match],
        first_contact_at=first_contact_at,
        last_contact_at=first_contact_at,
        now=now,
    )

    assert outcome is None


def test_matched_patient_without_any_usable_date_is_conservatively_not_a_lead() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    undated_match = PatientMatch(patient_id=uuid4(), branch_id=uuid4(), first_visit_at=None)

    outcome = resolve_lead_outcome(
        patient_matches=[undated_match],
        first_contact_at=now - timedelta(days=1),
        last_contact_at=now - timedelta(days=1),
        now=now,
    )

    assert outcome is None


def test_shared_number_with_one_pre_existing_and_one_new_patient_is_conservatively_not_a_lead() -> None:
    """A household phone matching two Patient rows, one that predates the
    contact and one that doesn't, must not be guessed either way -- the
    pre-existing relationship wins the conservative "not a lead" call."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    first_contact_at = now - timedelta(days=5)
    pre_existing = PatientMatch(
        patient_id=uuid4(), branch_id=uuid4(), first_visit_at=first_contact_at - timedelta(days=100)
    )
    newer = PatientMatch(
        patient_id=uuid4(), branch_id=uuid4(), first_visit_at=first_contact_at + timedelta(days=1)
    )

    outcome = resolve_lead_outcome(
        patient_matches=[pre_existing, newer],
        first_contact_at=first_contact_at,
        last_contact_at=first_contact_at,
        now=now,
    )

    assert outcome is None


def test_shared_number_with_two_won_candidates_picks_earliest_first_visit() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    first_contact_at = now - timedelta(days=20)
    earlier = PatientMatch(
        patient_id=uuid4(), branch_id=uuid4(), first_visit_at=first_contact_at + timedelta(days=1)
    )
    later = PatientMatch(
        patient_id=uuid4(), branch_id=uuid4(), first_visit_at=first_contact_at + timedelta(days=5)
    )

    outcome = resolve_lead_outcome(
        patient_matches=[later, earlier],
        first_contact_at=first_contact_at,
        last_contact_at=first_contact_at,
        now=now,
    )

    assert outcome == ("won", earlier.patient_id, earlier.branch_id)


# ---------------------------------------------------------------------------
# resolve_assignment
# ---------------------------------------------------------------------------


def test_kcell_extension_with_a_real_mapping_is_assigned() -> None:
    user_id = uuid4()
    assigned_user_id, status = resolve_assignment(
        first_source="kcell",
        first_external_user="101",
        kcell_assignment_by_extension={"101": user_id},
        whatsapp_current_assigned_user_id=None,
    )
    assert (assigned_user_id, status) == (user_id, "assigned")


def test_kcell_extension_never_configured_is_unresolved() -> None:
    assigned_user_id, status = resolve_assignment(
        first_source="kcell",
        first_external_user="999",
        kcell_assignment_by_extension={"101": uuid4()},
        whatsapp_current_assigned_user_id=None,
    )
    assert (assigned_user_id, status) == (None, "unresolved")


def test_kcell_extension_explicitly_marked_shared_is_ambiguous() -> None:
    assigned_user_id, status = resolve_assignment(
        first_source="kcell",
        first_external_user="front-desk",
        kcell_assignment_by_extension={"front-desk": None},
        whatsapp_current_assigned_user_id=None,
    )
    assert (assigned_user_id, status) == (None, "ambiguous")


def test_whatsapp_uses_current_assignment_as_a_best_effort_proxy() -> None:
    user_id = uuid4()
    assigned_user_id, status = resolve_assignment(
        first_source="whatsapp",
        first_external_user=None,
        kcell_assignment_by_extension={},
        whatsapp_current_assigned_user_id=user_id,
    )
    assert (assigned_user_id, status) == (user_id, "assigned")


def test_whatsapp_with_nobody_currently_assigned_is_unresolved() -> None:
    assigned_user_id, status = resolve_assignment(
        first_source="whatsapp",
        first_external_user=None,
        kcell_assignment_by_extension={},
        whatsapp_current_assigned_user_id=None,
    )
    assert (assigned_user_id, status) == (None, "unresolved")


# ---------------------------------------------------------------------------
# backfill_tenant -- integration-style, with the DB-touching helpers
# monkeypatched so only the write-path decisions (existing-lead check,
# dry-run short-circuit, insert) are exercised against a mocked session.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backfill_tenant_dry_run_never_touches_session_execute(monkeypatch) -> None:
    tenant_id = uuid4()
    phone_hash = "1" * 64
    now = datetime(2026, 6, 1, tzinfo=UTC)
    aggregate = ContactAggregate(
        first_at=now - timedelta(days=1),
        first_source="kcell",
        last_at=now - timedelta(days=1),
        first_external_user="101",
    )

    monkeypatch.setattr(backfill_leads, "_collect_events", AsyncMock(return_value=[]))
    monkeypatch.setattr(backfill_leads, "merge_contact_events", lambda events: {phone_hash: aggregate})
    monkeypatch.setattr(backfill_leads, "_patient_matches_by_hash", AsyncMock(return_value={}))
    monkeypatch.setattr(
        backfill_leads, "_kcell_assignment_map", AsyncMock(return_value={"101": None})
    )
    monkeypatch.setattr(backfill_leads, "_whatsapp_current_assignment", AsyncMock(return_value={}))

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)

    totals = await backfill_leads.backfill_tenant(session, tenant_id, now=now, dry_run=True)

    assert totals["contacts_scanned"] == 1
    assert totals["new"] == 1
    assert totals["ambiguous_assignment"] == 1
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_backfill_tenant_rerun_is_idempotent_when_lead_already_exists(monkeypatch) -> None:
    """Simulates a second run over a phone_hash the first run (or the live
    webhook path) already turned into a Lead: must skip, and must never
    attempt to write anything for it."""
    tenant_id = uuid4()
    phone_hash = "2" * 64
    now = datetime(2026, 6, 1, tzinfo=UTC)
    aggregate = ContactAggregate(
        first_at=now - timedelta(days=1), first_source="whatsapp", last_at=now - timedelta(days=1)
    )

    monkeypatch.setattr(backfill_leads, "_collect_events", AsyncMock(return_value=[]))
    monkeypatch.setattr(backfill_leads, "merge_contact_events", lambda events: {phone_hash: aggregate})
    monkeypatch.setattr(backfill_leads, "_patient_matches_by_hash", AsyncMock(return_value={}))
    monkeypatch.setattr(backfill_leads, "_kcell_assignment_map", AsyncMock(return_value={}))
    monkeypatch.setattr(backfill_leads, "_whatsapp_current_assignment", AsyncMock(return_value={}))

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=uuid4())  # a Lead already exists for this phone

    totals = await backfill_leads.backfill_tenant(session, tenant_id, now=now, dry_run=False)

    assert totals["skipped_existing_leads"] == 1
    assert totals["new"] == 0
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_backfill_tenant_empty_tenant_reports_all_zero_stats() -> None:
    tenant_id = uuid4()
    session = AsyncMock()
    session.execute = AsyncMock()
    session.execute.return_value.__iter__ = lambda self: iter([])

    totals = await backfill_leads.backfill_tenant(session, tenant_id, now=datetime(2026, 6, 1, tzinfo=UTC))

    for field in backfill_leads.STAT_FIELDS:
        assert totals[field] == 0
