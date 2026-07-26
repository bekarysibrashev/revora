from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class MLDatasetSnapshot(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "ml_dataset_snapshots"
    __table_args__ = (UniqueConstraint("tenant_id", "snapshot_key"),)

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    branch_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("branches.id", ondelete="SET NULL"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(100), index=True)
    snapshot_key: Mapped[str] = mapped_column(String(64))
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    row_count: Mapped[int] = mapped_column(Integer)
    positive_count: Mapped[int] = mapped_column(Integer)
    feature_schema: Mapped[dict] = mapped_column(JSONB)
    quality_report: Mapped[dict] = mapped_column(JSONB)
    source_max_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MLExperiment(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "ml_experiments"

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    dataset_snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ml_dataset_snapshots.id", ondelete="RESTRICT"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200))
    problem_type: Mapped[str] = mapped_column(String(50))
    target_name: Mapped[str] = mapped_column(String(100))
    algorithm: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), index=True)
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MLModelVersion(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "ml_model_versions"
    __table_args__ = (UniqueConstraint("tenant_id", "name", "version"),)

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    experiment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ml_experiments.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), index=True)
    artifact_uri: Mapped[str | None] = mapped_column(String(500))
    feature_schema: Mapped[dict] = mapped_column(JSONB)
    metrics: Mapped[dict] = mapped_column(JSONB)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MLPrediction(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "ml_predictions"

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    model_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ml_model_versions.id", ondelete="RESTRICT"), index=True
    )
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    score: Mapped[Decimal] = mapped_column(Numeric(8, 7))
    predicted_label: Mapped[str | None] = mapped_column(String(50))
    explanation: Mapped[dict] = mapped_column(JSONB, default=dict)
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actual_outcome: Mapped[str | None] = mapped_column(String(50))
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
