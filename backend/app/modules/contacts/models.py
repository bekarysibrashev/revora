from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class ContactIdentity(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "contact_identities"
    __table_args__ = (UniqueConstraint("tenant_id", "phone_hash"),)

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    phone_masked: Mapped[str | None] = mapped_column(String(30))
    phone_ciphertext: Mapped[str | None] = mapped_column(Text)
    first_inbound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    first_inbound_source: Mapped[str] = mapped_column(String(30), index=True)
    last_inbound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_inbound_source: Mapped[str] = mapped_column(String(30))
    inbound_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    call_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    message_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    was_known_patient: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
