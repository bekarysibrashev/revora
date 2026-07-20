"""Audit events for privileged and sensitive actions."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

class AuditLog(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "audit_log"
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True); entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True)); occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ip_address: Mapped[str | None] = mapped_column(INET); changes: Mapped[dict | None] = mapped_column(JSONB)
