"""API contracts for importing official 1C reports."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field


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
