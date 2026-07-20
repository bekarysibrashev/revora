"""Doctors, ratings and non-overlapping compensation history."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ExcludeConstraint, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Doctor(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "doctors"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(150))
    full_name: Mapped[str] = mapped_column(String(200), index=True)
    specialty: Mapped[str | None] = mapped_column(String(150))


class DoctorCompensationRule(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "doctor_compensation_rules"
    __table_args__ = (
        CheckConstraint("(percentage_value IS NULL) <> (fixed_amount IS NULL)", name="exactly_one_compensation_value"),
        CheckConstraint("percentage_value IS NULL OR percentage_value BETWEEN 0 AND 100", name="valid_percentage"),
        ExcludeConstraint(
            ("doctor_id", "="),
            (text("daterange(valid_from, COALESCE(valid_to, 'infinity'::date), '[]')"), "&&"),
            using="gist",
            name="exclude_overlapping_compensation",
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    doctor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), index=True)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    percentage_value: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    fixed_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="KZT")


class DoctorRating(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "doctor_ratings"
    __table_args__ = (UniqueConstraint("tenant_id", "doctor_id", "source", "rated_at"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    doctor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(50))
    rating: Mapped[Decimal] = mapped_column(Numeric(3, 2))
    reviews_count: Mapped[int]
    rated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
