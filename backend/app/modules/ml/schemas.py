from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class FeatureCoverage(BaseModel):
    name: str
    description: str
    available_count: int
    coverage_rate: Decimal
    usable: bool


class CohortMetric(BaseModel):
    dimension: str
    value: str
    label: str
    appointments: int
    no_shows: int
    no_show_rate: Decimal
    lift_vs_baseline: Decimal | None
    confidence_low: Decimal
    confidence_high: Decimal
    reliable: bool


class NoShowReadinessResponse(BaseModel):
    status: str
    status_reason: str
    row_count: int
    positive_count: int
    positive_rate: Decimal
    date_min: datetime | None
    date_max: datetime | None
    source_max_updated_at: datetime | None
    recommended_train_rows: int
    recommended_positive_rows: int
    feature_coverage: list[FeatureCoverage]
    cohorts: list[CohortMetric]
    date_from: date
    date_to: date
    branch_id: UUID | None
    generated_at: datetime


class DatasetSnapshotResponse(BaseModel):
    id: UUID
    purpose: str
    snapshot_key: str
    branch_id: UUID | None
    date_from: date
    date_to: date
    row_count: int
    positive_count: int
    feature_schema: dict[str, object]
    quality_report: dict[str, object]
    source_max_updated_at: datetime | None
    created_at: datetime


class DatasetSnapshotListResponse(BaseModel):
    items: list[DatasetSnapshotResponse]
    total: int


class MLRegistryResponse(BaseModel):
    dataset_snapshots: int
    experiments: int
    model_versions: int
    predictions: int
    active_model: bool
