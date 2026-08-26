"""Immutable control totals imported from official 1C reports."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, Date, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class OfficialReportImport(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "official_report_imports"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "report_type", "period_from", "period_to", "source_hash",
            name="uq_official_report_import_identity",
        ),
        Index(
            "ix_official_report_import_active_period",
            "tenant_id", "period_from", "period_to", "is_active",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    report_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)
    source_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    summary: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    metrics: Mapped[list["OfficialReportMetric"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )


class OfficialReportMetric(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "official_report_metrics"
    __table_args__ = (
        Index(
            "ix_official_report_metric_lookup",
            "tenant_id", "metric_code", "branch_id", "dimension_type",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    report_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("official_report_imports.id", ondelete="CASCADE"), index=True
    )
    branch_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("branches.id", ondelete="SET NULL"), index=True
    )
    dimension_type: Mapped[str] = mapped_column(String(30), nullable=False)
    dimension_key: Mapped[str] = mapped_column(String(300), nullable=False)
    dimension_label: Mapped[str] = mapped_column(String(500), nullable=False)
    metric_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="KZT", nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    report: Mapped[OfficialReportImport] = relationship(back_populates="metrics")
