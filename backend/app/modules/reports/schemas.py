"""API contracts for importing official 1C reports."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field


class CoverageInfoResponse(BaseModel):
    """Mirrors reports.repository.CoverageInfo for API responses: how much
    of a requested date range a metric's value is actually backed by."""

    requested_from: date
    requested_to: date
    covered_from: date | None
    covered_to: date | None
    covered_months: list[str] = Field(default_factory=list)
    missing_months: list[str] = Field(default_factory=list)
    coverage_ratio: float = 0.0
    is_partial: bool = False
    is_exact: bool = False


class CardStatusResponse(BaseModel):
    """Mirrors reports.card_status.CardStatus for API responses -- the
    contract every "official 1C figure vs local detail" dashboard card is
    delivered through: never a bare number, always its status/source/
    coverage so the frontend can render an honest "Не хватает данных"
    instead of a silently fabricated value.
    """

    metric_code: str
    label: str
    official_value: Decimal | None
    detail_value: Decimal | None
    difference: Decimal | None
    status: Literal["verified", "mismatch", "partial", "unavailable", "pending"]
    source_report: str
    coverage_from: date | None
    coverage_to: date | None
    branch: str | None = None
    reason: str | None = None
    depends_on: tuple[str, ...] = ()
    unit: str = "KZT"


class OfficialReportResponse(BaseModel):
    id: UUID
    report_type: str
    report_label: str
    period_from: date
    period_to: date
    source_filename: str
    source_hash: str
    metrics_count: int
    summary: dict
    is_active: bool
    imported_at: datetime
    duplicate: bool = False


class OfficialReportListResponse(BaseModel):
    items: list[OfficialReportResponse]
    total: int
    required_report_types: list[str]


class OneCReportMetricInput(BaseModel):
    dimension_type: str = Field(min_length=1, max_length=30)
    dimension_key: str = Field(min_length=1, max_length=300)
    dimension_label: str = Field(min_length=1, max_length=500)
    metric_code: str = Field(min_length=1, max_length=80)
    value: Decimal
    unit: Literal["KZT", "count"] = "KZT"
    branch_key: str | None = Field(default=None, max_length=100)
    details: dict = Field(default_factory=dict)


class OneCReportSnapshotRequest(BaseModel):
    report_type: Literal[
        "cash_receipts",
        "service_revenue",
        "payroll",
        "doctor_revenue",
        "purchases",
        "patients",
        "appointments",
    ]
    period_from: date
    period_to: date
    metrics: list[OneCReportMetricInput] = Field(min_length=1, max_length=10000)
    summary: dict = Field(default_factory=dict)


class OneCReportSnapshotBatchRequest(BaseModel):
    snapshots: list[OneCReportSnapshotRequest] = Field(min_length=1, max_length=250)


class OneCReportSnapshotBatchResponse(BaseModel):
    items: list[OfficialReportResponse]
    total: int
