"""Human classification feedback and deterministic analytical insights."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

class AIClassificationFeedback(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "ai_classification_feedback"
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    transaction_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("raw_bank_transactions.id", ondelete="CASCADE"), index=True)
    predicted_category_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("expense_categories.id"))
    corrected_category_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("expense_categories.id"))
    corrected_by_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    model_version: Mapped[str | None] = mapped_column(String(100))

class AIInsight(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "ai_insights"
    __table_args__ = (UniqueConstraint("tenant_id", "fingerprint"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("branches.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64)); insight_type: Mapped[str] = mapped_column(String(50), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True); title: Mapped[str] = mapped_column(String(250))
    description: Mapped[str] = mapped_column(Text); evidence: Mapped[dict] = mapped_column(JSONB)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class AIInsightRead(TimestampMixin, Base):
    __tablename__ = "ai_insight_reads"
    insight_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ai_insights.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
