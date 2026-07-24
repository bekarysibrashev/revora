"""Audit record of every accepted Kcell callback (without storing its secret token)."""
from uuid import UUID
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

class KcellWebhookReceipt(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "kcell_webhook_receipts"
    __table_args__ = (UniqueConstraint("tenant_id", "call_id", "command"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    call_id: Mapped[str] = mapped_column(String(200), index=True)
    command: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSONB)
