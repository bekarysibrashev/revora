from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class WhatsAppChannel(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_channels"
    __table_args__ = (UniqueConstraint("tenant_id", "phone_number_id"),)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    phone_number_id: Mapped[str] = mapped_column(String(80), index=True)
    waba_id: Mapped[str | None] = mapped_column(String(80))
    display_name: Mapped[str] = mapped_column(String(150))
    business_number_masked: Mapped[str | None] = mapped_column(String(30))
    access_token_ciphertext: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    connection_mode: Mapped[str] = mapped_column(String(30), default="manual")
    status: Mapped[str] = mapped_column(String(30), default="test")
    bot_mode: Mapped[str] = mapped_column(String(20), default="draft")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_webhook_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))


class WhatsAppConversation(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_conversations"
    __table_args__ = (UniqueConstraint("tenant_id", "channel_id", "contact_hash"),)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("whatsapp_channels.id", ondelete="CASCADE"), index=True)
    contact_hash: Mapped[str] = mapped_column(String(64), index=True)
    contact_ciphertext: Mapped[str] = mapped_column(Text)
    contact_masked: Mapped[str] = mapped_column(String(30))
    state: Mapped[str] = mapped_column(String(30), default="bot_active", index=True)
    language: Mapped[str] = mapped_column(String(5), default="ru")
    assigned_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    handoff_reason: Mapped[str | None] = mapped_column(String(300))
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_patient_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unread_count: Mapped[int] = mapped_column(Integer, default=0)


class WhatsAppMessage(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_messages"
    __table_args__ = (UniqueConstraint("tenant_id", "external_message_id"),)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("whatsapp_conversations.id", ondelete="CASCADE"), index=True)
    external_message_id: Mapped[str] = mapped_column(String(160), index=True)
    direction: Mapped[str] = mapped_column(String(10))
    sender_kind: Mapped[str] = mapped_column(String(20))
    message_type: Mapped[str] = mapped_column(String(30), default="text")
    body_ciphertext: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="received")
    is_draft: Mapped[bool] = mapped_column(Boolean, default=False)
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WhatsAppKnowledgeItem(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_knowledge_items"
    __table_args__ = (UniqueConstraint("tenant_id", "source"),)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(300))
    content_ru: Mapped[str | None] = mapped_column(Text)
    content_kk: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list] = mapped_column(JSONB, default=list)
    risk_level: Mapped[str] = mapped_column(String(30), default="review")
    source: Mapped[str] = mapped_column(String(250))
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    approved_by_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WhatsAppAIUsage(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_ai_usage"

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("whatsapp_conversations.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_kzt: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
