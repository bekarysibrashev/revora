from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.reports.schemas import OneCReportSnapshotRequest
from app.modules.reports.service import OfficialReportsService


class FakeReportsRepository:
    def __init__(self):
        self.report = None
        self.branch = SimpleNamespace(
            id=uuid4(), code="seifullina", name="SAN (Сейфуллина)"
        )

    async def branches_by_code(self, tenant_id):
        return {self.branch.code: self.branch}

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
