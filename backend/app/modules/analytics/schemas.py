from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class DatasetHealth(BaseModel):
    key: str
    name: str
    record_count: int
    latest_at: datetime | None
    status: str
    scope: str


class QualityIssue(BaseModel):
    code: str
    name: str
    description: str
    severity: str
    affected_records: int
    dataset: str


class ConnectionHealth(BaseModel):
    id: UUID
    provider: str
    name: str
    status: str
    last_sync_at: datetime | None
    last_sync_status: str | None


class DataQualitySummary(BaseModel):
    score: int
    status: str
    ready_datasets: int
    total_datasets: int
    critical_issues: int
    warning_issues: int


class DataQualityResponse(BaseModel):
    summary: DataQualitySummary
    datasets: list[DatasetHealth]
    issues: list[QualityIssue]
    connections: list[ConnectionHealth]
    date_from: date
    date_to: date
    branch_id: UUID | None
    generated_at: datetime


class MetricDefinition(BaseModel):
    key: str
    name: str
    group: str
    description: str
    formula: str
    required_datasets: list[str]
    available: bool
    missing_datasets: list[str]


class MetricCatalogResponse(BaseModel):
    items: list[MetricDefinition]
    available: int
    total: int
    date_from: date
    date_to: date
    branch_id: UUID | None
    generated_at: datetime
