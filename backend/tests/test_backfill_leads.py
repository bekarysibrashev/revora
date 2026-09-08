from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.cli.backfill_leads import decide_lead_state, merge_contact_events


def test_merge_keeps_earliest_source_and_latest_contact() -> None:
    phone_hash = "a" * 64
    other_hash = "b" * 64
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    events = [
        (phone_hash, "whatsapp", t0 + timedelta(hours=5)),
        (phone_hash, "kcell", t0),  # earlier -- becomes the first_source
        (phone_hash, "whatsapp", t0 + timedelta(days=2)),  # later -- becomes last_at
        (other_hash, "whatsapp", t0),
    ]

    merged = merge_contact_events(events)

    assert set(merged) == {phone_hash, other_hash}
    assert merged[phone_hash].first_source == "kcell"
    assert merged[phone_hash].first_at == t0
    assert merged[phone_hash].last_at == t0 + timedelta(days=2)


def test_merge_single_event_is_its_own_first_and_last() -> None:
    phone_hash = "c" * 64
    occurred_at = datetime(2026, 5, 1, 9, tzinfo=UTC)

    merged = merge_contact_events([(phone_hash, "kcell", occurred_at)])

    assert merged[phone_hash].first_at == occurred_at
    assert merged[phone_hash].last_at == occurred_at
    assert merged[phone_hash].first_source == "kcell"


def test_decide_lead_state_wins_when_patient_matched_and_copies_real_branch() -> None:
    patient_id = uuid4()
    branch_id = uuid4()
    now = datetime(2026, 6, 1, tzinfo=UTC)

    status, resolved_patient_id, resolved_branch_id = decide_lead_state(
        matched_patient_id=patient_id,
        matched_patient_branch_id=branch_id,
        last_contact_at=now - timedelta(days=400),  # ancient contact, irrelevant once won
        now=now,
    )

    assert status == "won"
    assert resolved_patient_id == patient_id
    assert resolved_branch_id == branch_id


def test_decide_lead_state_never_guesses_a_branch_for_new_or_lost() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)

    new_status, new_patient, new_branch = decide_lead_state(
        matched_patient_id=None,
        matched_patient_branch_id=None,
        last_contact_at=now - timedelta(days=1),
        now=now,
    )
    lost_status, lost_patient, lost_branch = decide_lead_state(
        matched_patient_id=None,
        matched_patient_branch_id=None,
        last_contact_at=now - timedelta(days=30),
        now=now,
    )

    assert (new_status, new_patient, new_branch) == ("new", None, None)
    assert (lost_status, lost_patient, lost_branch) == ("lost", None, None)


def test_decide_lead_state_boundary_is_exactly_lost_lead_days() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)

    just_inside, _, _ = decide_lead_state(
        matched_patient_id=None,
        matched_patient_branch_id=None,
        last_contact_at=now - timedelta(days=14) + timedelta(seconds=1),
        now=now,
    )
    exactly_at, _, _ = decide_lead_state(
        matched_patient_id=None,
        matched_patient_branch_id=None,
        last_contact_at=now - timedelta(days=14),
        now=now,
    )

    assert just_inside == "new"
    assert exactly_at == "lost"
