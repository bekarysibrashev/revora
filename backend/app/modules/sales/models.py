"""Canonical patient, lead, call and appointment entities."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Patient(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "patients"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(150))
    full_name: Mapped[str | None] = mapped_column(String(200))
    phone_e164_encrypted: Mapped[str | None] = mapped_column(Text)
    phone_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    lead_source: Mapped[str | None] = mapped_column(String(100))


class Lead(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    patient_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("patients.id"))
    assigned_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(150))
    source: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), index=True)


class Call(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "calls"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("branches.id"))
    lead_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("leads.id"))
    external_id: Mapped[str] = mapped_column(String(150))
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_seconds: Mapped[int | None]
    outcome: Mapped[str | None] = mapped_column(String(50))


class ServiceDirection(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "service_directions"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(150))
    name: Mapped[str] = mapped_column(String(200))


class Appointment(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    patient_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("doctors.id"), index=True)
    direction_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("service_directions.id"))
    external_id: Mapped[str] = mapped_column(String(150))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(50), index=True)


class TreatmentPlan(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "treatment_plans"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("patients.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(150))
    status: Mapped[str] = mapped_column(String(50))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
