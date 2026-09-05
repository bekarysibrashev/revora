"""Direct, DB-free unit tests for the patient_phone_identity row-building
rules used by OfficialReportsRepository.upsert_patient_identities. Kept as
a standalone pure function (_build_patient_identity_row) specifically so
these rules -- phone_hash validation, the deleted-patient flag, and date
parsing -- are testable without a live Postgres connection.
"""
from datetime import UTC, datetime
from uuid import uuid4

from app.modules.reports.repository import _build_patient_identity_row, _parse_snapshot_date, _positive_int


def _metric(**overrides) -> dict:
    base = {
        "metric_code": "patient_phone_identity",
        "dimension_key": "patient-external-1",
        "dimension_label": "Иванова Айгуль",
        "branch_id": None,
        "details": {
            "phone_hash": "a" * 64,
            "full_name": "Иванова Айгуль",
            "first_visit_at": "2025-01-10",
            "last_visit_at": "2026-07-02",
            "visit_count": 4,
            "active": True,
        },
    }
    base.update(overrides)
    return base


def test_builds_a_full_row_for_a_well_formed_identity_metric() -> None:
    tenant_id = uuid4()

    row = _build_patient_identity_row(tenant_id, _metric())

    assert row is not None
    assert row["tenant_id"] == tenant_id
    assert row["external_id"] == "patient-external-1"
    assert row["phone_hash"] == "a" * 64
    assert row["visit_count"] == 4
    assert row["is_active"] is True
    assert row["first_visit_at"] == datetime(2025, 1, 10, tzinfo=UTC)
    assert row["last_visit_at"] == datetime(2026, 7, 2, tzinfo=UTC)


def test_ignores_a_non_identity_metric_code() -> None:
    assert _build_patient_identity_row(uuid4(), _metric(metric_code="patient_seen")) is None


def test_skips_a_row_with_no_stable_external_id() -> None:
    assert _build_patient_identity_row(uuid4(), _metric(dimension_key="")) is None
    assert _build_patient_identity_row(uuid4(), _metric(dimension_key="empty")) is None


def test_drops_a_malformed_phone_hash_but_keeps_the_patient() -> None:
    metric = _metric(details={**_metric()["details"], "phone_hash": "not-a-sha256"})

    row = _build_patient_identity_row(uuid4(), metric)

    assert row is not None
    assert row["phone_hash"] is None
    assert row["external_id"] == "patient-external-1"


def test_a_deleted_1c_patient_is_stored_as_inactive_not_dropped() -> None:
    metric = _metric(details={**_metric()["details"], "active": False})

    row = _build_patient_identity_row(uuid4(), metric)

    assert row is not None
    assert row["is_active"] is False
    # A deleted patient still keeps its phone_hash on file -- ContactRegistry
    # (via the is_active filter added to ContactRepository) is responsible
    # for not treating it as a live match, not this ingestion step.
    assert row["phone_hash"] == "a" * 64


def test_two_different_patients_can_share_one_phone_hash() -> None:
    shared_hash = "b" * 64
    tenant_id = uuid4()

    row_a = _build_patient_identity_row(
        tenant_id,
        _metric(dimension_key="patient-a", details={**_metric()["details"], "phone_hash": shared_hash}),
    )
    row_b = _build_patient_identity_row(
        tenant_id,
        _metric(dimension_key="patient-b", details={**_metric()["details"], "phone_hash": shared_hash}),
    )

    assert row_a is not None and row_b is not None
    assert row_a["external_id"] != row_b["external_id"]
    assert row_a["phone_hash"] == row_b["phone_hash"] == shared_hash


def test_full_name_falls_back_to_dimension_label_when_details_omit_it() -> None:
    metric = _metric(details={k: v for k, v in _metric()["details"].items() if k != "full_name"})

    row = _build_patient_identity_row(uuid4(), metric)

    assert row is not None
    assert row["full_name"] == metric["dimension_label"]


def test_missing_visit_count_defaults_to_zero_not_a_crash() -> None:
    metric = _metric(details={**_metric()["details"], "visit_count": "not-a-number"})

    row = _build_patient_identity_row(uuid4(), metric)

    assert row is not None
    assert row["visit_count"] == 0


def test_parse_snapshot_date_accepts_plain_date_and_iso_datetime() -> None:
    assert _parse_snapshot_date("2026-07-02") == datetime(2026, 7, 2, tzinfo=UTC)
    assert _parse_snapshot_date("2026-07-02T10:30:00Z") == datetime(2026, 7, 2, 10, 30, tzinfo=UTC)
    assert _parse_snapshot_date(None) is None
    assert _parse_snapshot_date("") is None
    assert _parse_snapshot_date("not-a-date") is None


def test_positive_int_rejects_zero_negative_and_unparsable_values() -> None:
    assert _positive_int(4) == 4
    assert _positive_int("4") == 4
    assert _positive_int(0) == 0
    assert _positive_int(-3) == 0
    assert _positive_int(None) == 0
    assert _positive_int("not-a-number") == 0
