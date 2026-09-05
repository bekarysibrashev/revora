from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.reports.schemas import OneCReportSnapshotRequest
from app.modules.reports.service import OfficialReportsService


class FakeReportsRepository:
    def __init__(self, extra_branches: list | None = None):
        self.report = None
        self.branch = SimpleNamespace(
            id=uuid4(), code="seifullina", name="SAN (Сейфуллина)"
        )
        self.extra_branches = extra_branches or []
        self.upserted_patient_identity_calls: list[list[dict]] = []

    async def branches_by_code(self, tenant_id):
        result = {self.branch.code: self.branch}
        for branch in self.extra_branches:
            result[branch.code] = branch
        return result

    async def duplicate(self, *args):
        return None

    async def replace_active(self, **kwargs):
        self.report = SimpleNamespace(
            id=uuid4(),
            report_type=kwargs["report_type"],
            period_from=kwargs["period_from"],
            period_to=kwargs["period_to"],
            source_filename=kwargs["source_filename"],
            source_hash=kwargs["source_hash"],
            metrics=[SimpleNamespace(**item) for item in kwargs["metrics"]],
            summary=kwargs["summary"],
            is_active=True,
            created_at=datetime.now(UTC),
        )
        return self.report

    async def upsert_patient_identities(self, tenant_id, metrics):
        self.upserted_patient_identity_calls.append(metrics)
        return sum(1 for item in metrics if item["metric_code"] == "patient_phone_identity")


@pytest.mark.asyncio
async def test_connector_snapshot_resolves_one_c_branch_and_replaces_period() -> None:
    repository = FakeReportsRepository()
    service = OfficialReportsService(repository)
    tenant_id = uuid4()
    connection_id = uuid4()
    payload = OneCReportSnapshotRequest.model_validate({
        "report_type": "service_revenue",
        "period_from": "2026-07-01",
        "period_to": "2026-07-31",
        "metrics": [
            {
                "dimension_type": "clinic",
                "dimension_key": "clinic",
                "dimension_label": "Вся клиника",
                "metric_code": "revenue_accrual",
                "value": "65994689.65",
            },
            {
                "dimension_type": "branch",
                "dimension_key": "branch-guid",
                "dimension_label": "SAN (Сейфуллина)",
                "metric_code": "revenue_accrual",
                "value": "30331339.88",
                "branch_key": "STRUCTURAL-UNIT-GUID",
            },
        ],
    })

    response = await service.ingest_connector_snapshot(
        tenant_id=tenant_id,
        connection_id=connection_id,
        branch_code_map={"structural-unit-guid": "seifullina"},
        payload=payload,
    )

    assert response.report_type == "service_revenue"
    assert repository.report.metrics[0].branch_id is None
    assert repository.report.metrics[1].branch_id == repository.branch.id
    assert repository.report.source_filename.endswith(":service_revenue")


@pytest.mark.asyncio
async def test_connector_snapshot_maps_branch_from_snapshot_without_odata() -> None:
    repository = FakeReportsRepository()
    service = OfficialReportsService(repository)
    payload = OneCReportSnapshotRequest.model_validate({
        "report_type": "payroll",
        "period_from": date(2026, 7, 1),
        "period_to": date(2026, 7, 31),
        "metrics": [{
            "dimension_type": "branch",
            "dimension_key": "branch-guid",
            "dimension_label": "SAN (Сейфуллина)",
            "metric_code": "payroll_accrual",
            "value": 1,
            "branch_key": "structural-unit-guid",
        }],
    })

    await service.ingest_connector_snapshot(
        tenant_id=uuid4(), connection_id=uuid4(),
        branch_code_map={}, payload=payload,
    )

    assert repository.report.metrics[0].branch_id == repository.branch.id


@pytest.mark.asyncio
async def test_connector_snapshot_keeps_clinic_total_when_branch_is_unmapped() -> None:
    repository = FakeReportsRepository()
    service = OfficialReportsService(repository)
    payload = OneCReportSnapshotRequest.model_validate({
        "report_type": "payroll",
        "period_from": date(2026, 7, 1),
        "period_to": date(2026, 7, 31),
        "metrics": [
            {
                "dimension_type": "branch",
                "dimension_key": "unknown-guid",
                "dimension_label": "Служебное подразделение",
                "metric_code": "payroll_accrual",
                "value": 1,
                "branch_key": "unknown-guid",
            },
            {
                "dimension_type": "clinic",
                "dimension_key": "clinic",
                "dimension_label": "Вся клиника",
                "metric_code": "payroll_accrual",
                "value": 10,
            },
        ],
    })

    await service.ingest_connector_snapshot(
        tenant_id=uuid4(), connection_id=uuid4(),
        branch_code_map={}, payload=payload,
    )

    assert len(repository.report.metrics) == 1
    assert repository.report.metrics[0].dimension_type == "clinic"
    assert repository.report.summary["unmapped_branches"] == [{
        "source_key": "unknown-guid",
        "source_label": "Служебное подразделение",
    }]


@pytest.mark.asyncio
async def test_connector_accepts_anonymous_patient_markers() -> None:
    repository = FakeReportsRepository()
    service = OfficialReportsService(repository)
    payload = OneCReportSnapshotRequest.model_validate({
        "report_type": "patients",
        "period_from": date(2026, 7, 2),
        "period_to": date(2026, 7, 2),
        "metrics": [{
            "dimension_type": "patient",
            "dimension_key": "patient-guid-without-name",
            "dimension_label": "Обезличенный пациент",
            "metric_code": "patient_seen",
            "value": 1,
            "unit": "count",
            "branch_key": "structural-unit-guid",
        }],
        "summary": {"granularity": "day"},
    })

    await service.ingest_connector_snapshot(
        tenant_id=uuid4(), connection_id=uuid4(),
        branch_code_map={"structural-unit-guid": "seifullina"}, payload=payload,
    )

    assert repository.report.metrics[0].metric_code == "patient_seen"
    assert repository.report.metrics[0].dimension_label == "Обезличенный пациент"


@pytest.mark.asyncio
async def test_connector_snapshot_upserts_patient_identity_and_never_touches_plaintext_phone() -> None:
    repository = FakeReportsRepository()
    service = OfficialReportsService(repository)
    payload = OneCReportSnapshotRequest.model_validate({
        "report_type": "patients",
        "period_from": date(2026, 7, 2),
        "period_to": date(2026, 7, 2),
        "metrics": [
            {
                "dimension_type": "patient",
                "dimension_key": "patient-external-1",
                "dimension_label": "Иванова Айгуль",
                "metric_code": "patient_phone_identity",
                "value": 1,
                "unit": "count",
                "branch_key": "structural-unit-guid",
                "details": {
                    "phone_hash": "a" * 64,
                    "full_name": "Иванова Айгуль",
                    "first_visit_at": "2025-01-10",
                    "last_visit_at": "2026-07-02",
                    "visit_count": 4,
                    "active": True,
                },
            },
            {
                "dimension_type": "patient",
                "dimension_key": "patient-guid-without-name",
                "dimension_label": "Обезличенный пациент",
                "metric_code": "patient_seen",
                "value": 1,
                "unit": "count",
                "branch_key": "structural-unit-guid",
            },
        ],
    })

    await service.ingest_connector_snapshot(
        tenant_id=uuid4(), connection_id=uuid4(),
        branch_code_map={"structural-unit-guid": "seifullina"}, payload=payload,
    )

    assert len(repository.upserted_patient_identity_calls) == 1
    upserted = repository.upserted_patient_identity_calls[0]
    identity_rows = [m for m in upserted if m["metric_code"] == "patient_phone_identity"]
    assert len(identity_rows) == 1
    row = identity_rows[0]
    assert row["dimension_key"] == "patient-external-1"
    assert row["details"]["phone_hash"] == "a" * 64
    assert "phone" not in row["details"] or row["details"].get("phone") is None
    # patient_seen (the pre-existing anonymized marker) is untouched and still
    # lands in official_report_metrics alongside the identity row.
    assert any(m["metric_code"] == "patient_seen" for m in upserted)


@pytest.mark.asyncio
async def test_connector_ingests_a_batch_of_daily_snapshots() -> None:
    repository = FakeReportsRepository()
    service = OfficialReportsService(repository)
    snapshots = [
        OneCReportSnapshotRequest.model_validate({
            "report_type": report_type,
            "period_from": date(2026, 7, 2),
            "period_to": date(2026, 7, 2),
            "metrics": [{
                "dimension_type": "clinic",
                "dimension_key": "clinic",
                "dimension_label": "Вся клиника",
                "metric_code": metric_code,
                "value": value,
            }],
            "summary": {"granularity": "day"},
        })
        for report_type, metric_code, value in [
            ("service_revenue", "revenue_accrual", 100),
            ("cash_receipts", "revenue_payment", 80),
        ]
    ]

    response = await service.ingest_connector_snapshots(
        tenant_id=uuid4(), connection_id=uuid4(), branch_code_map={},
        snapshots=snapshots,
    )

    assert response.total == 2
    assert [item.report_type for item in response.items] == [
        "service_revenue", "cash_receipts",
    ]


@pytest.mark.asyncio
async def test_connector_snapshot_resolves_a_distinct_branch_per_patient_identity_row() -> None:
    second_branch = SimpleNamespace(id=uuid4(), code="abay", name="ABA (Абая)")
    repository = FakeReportsRepository(extra_branches=[second_branch])
    service = OfficialReportsService(repository)
    payload = OneCReportSnapshotRequest.model_validate({
        "report_type": "patients",
        "period_from": date(2026, 7, 2),
        "period_to": date(2026, 7, 2),
        "metrics": [
            {
                "dimension_type": "patient",
                "dimension_key": "patient-branch-a",
                "dimension_label": "Пациент филиала Сейфуллина",
                "metric_code": "patient_phone_identity",
                "value": 1,
                "unit": "count",
                "branch_key": "structural-unit-guid",
                "details": {"phone_hash": "c" * 64, "active": True},
            },
            {
                "dimension_type": "patient",
                "dimension_key": "patient-branch-b",
                "dimension_label": "Пациент филиала Абая",
                "metric_code": "patient_phone_identity",
                "value": 1,
                "unit": "count",
                "branch_key": "abay-unit-guid",
                "details": {"phone_hash": "d" * 64, "active": True},
            },
        ],
    })

    await service.ingest_connector_snapshot(
        tenant_id=uuid4(), connection_id=uuid4(),
        branch_code_map={"structural-unit-guid": "seifullina", "abay-unit-guid": "abay"},
        payload=payload,
    )

    upserted = repository.upserted_patient_identity_calls[0]
    rows_by_key = {m["dimension_key"]: m for m in upserted if m["metric_code"] == "patient_phone_identity"}
    assert rows_by_key["patient-branch-a"]["branch_id"] == repository.branch.id
    assert rows_by_key["patient-branch-b"]["branch_id"] == second_branch.id
    assert rows_by_key["patient-branch-a"]["branch_id"] != rows_by_key["patient-branch-b"]["branch_id"]


@pytest.mark.asyncio
async def test_connector_snapshot_keeps_two_distinct_patients_sharing_one_phone_number() -> None:
    repository = FakeReportsRepository()
    service = OfficialReportsService(repository)
    shared_hash = "e" * 64
    payload = OneCReportSnapshotRequest.model_validate({
        "report_type": "patients",
        "period_from": date(2026, 7, 2),
        "period_to": date(2026, 7, 2),
        "metrics": [
            {
                "dimension_type": "patient",
                "dimension_key": "family-member-1",
                "dimension_label": "Иванов Асхат",
                "metric_code": "patient_phone_identity",
                "value": 1,
                "unit": "count",
                "branch_key": "structural-unit-guid",
                "details": {"phone_hash": shared_hash, "active": True},
            },
            {
                "dimension_type": "patient",
                "dimension_key": "family-member-2",
                "dimension_label": "Иванова Айгуль",
                "metric_code": "patient_phone_identity",
                "value": 1,
                "unit": "count",
                "branch_key": "structural-unit-guid",
                "details": {"phone_hash": shared_hash, "active": True},
            },
        ],
    })

    await service.ingest_connector_snapshot(
        tenant_id=uuid4(), connection_id=uuid4(),
        branch_code_map={"structural-unit-guid": "seifullina"}, payload=payload,
    )

    upserted = repository.upserted_patient_identity_calls[0]
    identity_rows = [m for m in upserted if m["metric_code"] == "patient_phone_identity"]
    assert len(identity_rows) == 2
    assert {row["dimension_key"] for row in identity_rows} == {"family-member-1", "family-member-2"}
    assert all(row["details"]["phone_hash"] == shared_hash for row in identity_rows)


@pytest.mark.asyncio
async def test_connector_snapshot_passes_through_a_deleted_patients_active_flag() -> None:
    repository = FakeReportsRepository()
    service = OfficialReportsService(repository)
    payload = OneCReportSnapshotRequest.model_validate({
        "report_type": "patients",
        "period_from": date(2026, 7, 2),
        "period_to": date(2026, 7, 2),
        "metrics": [{
            "dimension_type": "patient",
            "dimension_key": "patient-deleted-1",
            "dimension_label": "Удалённый пациент",
            "metric_code": "patient_phone_identity",
            "value": 1,
            "unit": "count",
            "branch_key": "structural-unit-guid",
            "details": {"phone_hash": "f" * 64, "active": False},
        }],
    })

    await service.ingest_connector_snapshot(
        tenant_id=uuid4(), connection_id=uuid4(),
        branch_code_map={"structural-unit-guid": "seifullina"}, payload=payload,
    )

    upserted = repository.upserted_patient_identity_calls[0]
    row = next(m for m in upserted if m["metric_code"] == "patient_phone_identity")
    assert row["details"]["active"] is False


@pytest.mark.asyncio
async def test_connector_accepts_the_full_1c_extension_patient_identity_wire_shape() -> None:
    """Payload validator: this is the exact JSON shape РвОбменСервер.bsl's
    ПостроитьДеталиИдентичностиПациента + ДобавитьМетрику build for a
    patient_phone_identity row (extension 1.2.0). If the extension's wire
    format ever drifts from what OneCReportSnapshotRequest accepts, this
    test is the one that should fail first.
    """
    repository = FakeReportsRepository()
    service = OfficialReportsService(repository)
    payload = OneCReportSnapshotRequest.model_validate({
        "report_type": "patients",
        "period_from": "2026-07-01",
        "period_to": "2026-07-31",
        "metrics": [{
            "dimension_type": "patient",
            "dimension_key": "3f9c9f2e-1111-4a11-9a11-abcdefabcdef",
            "dimension_label": "Иванова Айгуль Ануаровна",
            "metric_code": "patient_phone_identity",
            "value": 1,
            "unit": "count",
            "branch_key": "structural-unit-guid",
            "details": {
                "phone_hash": "5cf2fca546400423fc2c6f57227faa6a058a191ce936762760def12e43532e76",
                "full_name": "Иванова Айгуль Ануаровна",
                "first_visit_at": "2025-01-10",
                "last_visit_at": "2026-07-02",
                "visit_count": 4,
                "active": True,
                "updated_at": "2026-07-31",
            },
        }],
        "summary": {"source": "1c", "extension_version": "1.2.0", "granularity": "period"},
    })

    response = await service.ingest_connector_snapshot(
        tenant_id=uuid4(), connection_id=uuid4(),
        branch_code_map={"structural-unit-guid": "seifullina"}, payload=payload,
    )

    assert response.report_type == "patients"
    upserted = repository.upserted_patient_identity_calls[0]
    row = upserted[0]
    assert row["details"]["phone_hash"] == "5cf2fca546400423fc2c6f57227faa6a058a191ce936762760def12e43532e76"
    assert row["details"]["active"] is True
    # phone_hash must be a well-formed 64-char SHA-256 hex digest, mirroring
    # what НормализоватьТелефон/ХэшТелефона in the extension always produces.
    assert len(row["details"]["phone_hash"]) == 64
    int(row["details"]["phone_hash"], 16)  # raises ValueError if not hex
