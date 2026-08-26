"""API contracts for importing official 1C reports."""

from datetime import date, datetime
from uuid import UUID
from pydantic import BaseModel


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
