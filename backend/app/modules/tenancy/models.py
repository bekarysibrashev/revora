"""Clinic tenants and their branches."""

from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Almaty", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="KZT", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    branches: Mapped[list["Branch"]] = relationship(back_populates="tenant")


class Branch(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    tenant: Mapped[Tenant] = relationship(back_populates="branches")
