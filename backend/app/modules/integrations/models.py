"""Source connections, raw ingestion, mapping and transformation lineage."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class IntegrationConnection(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "integration_connections"
    __table_args__ = (UniqueConstraint("tenant_id", "provider", "name"),)

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(150))
    status: Mapped[str] = mapped_column(String(30), index=True)
    encrypted_credentials: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)


class SyncRun(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "sync_runs"

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    connection_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("integration_connections.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(30), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_read: Mapped[int] = mapped_column(default=0)
    records_written: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text)


class MappingProfile(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Versioned translation rules for one tenant, source and entity pair."""

    __tablename__ = "mapping_profiles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "connection_id", "source_entity", "target_entity", "version"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    connection_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("integration_connections.id", ondelete="CASCADE"),
        index=True,
    )
    source_entity: Mapped[str] = mapped_column(String(100), index=True)
    target_entity: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[int] = mapped_column(Integer)
    rules: Mapped[dict] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class RawRecord(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Immutable source row retained for audit and repeatable processing."""

    __tablename__ = "raw_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "connection_id", "source_entity", "record_hash"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    connection_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("integration_connections.id", ondelete="CASCADE"),
        index=True,
    )
    sync_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sync_runs.id", ondelete="SET NULL"), index=True
    )
    source_entity: Mapped[str] = mapped_column(String(100), index=True)
    source_record_id: Mapped[str | None] = mapped_column(String(200), index=True)
    source_schema_version: Mapped[str | None] = mapped_column(String(100))
    record_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class NormalizationError(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """A quarantined row-level or field-level mapping problem."""

    __tablename__ = "normalization_errors"

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    raw_record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("raw_records.id", ondelete="CASCADE"), index=True
    )
    mapping_profile_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("mapping_profiles.id", ondelete="SET NULL")
    )
    error_code: Mapped[str] = mapped_column(String(80), index=True)
    message: Mapped[str] = mapped_column(Text)
    field_name: Mapped[str | None] = mapped_column(String(150))
    raw_value: Mapped[object | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecordLineage(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Trace a canonical record back to its raw row and mapping version."""

    __tablename__ = "record_lineage"
    __table_args__ = (
        UniqueConstraint("raw_record_id", "target_entity", "target_record_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    raw_record_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("raw_records.id", ondelete="CASCADE"), index=True
    )
    mapping_profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("mapping_profiles.id", ondelete="RESTRICT")
    )
    target_entity: Mapped[str] = mapped_column(String(100), index=True)
    target_record_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    transformed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
