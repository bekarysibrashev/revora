"""Persistent, versioned rules and results for call quality control."""
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class CallQualityRuleSet(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "call_quality_rule_sets"
    __table_args__ = (UniqueConstraint("tenant_id", "version"),)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(150))
    success_definition: Mapped[str] = mapped_column(Text)
    partial_success_definition: Mapped[str] = mapped_column(Text)
    loss_definition: Mapped[str] = mapped_column(Text)
    criteria: Mapped[list[dict]] = mapped_column(JSONB)
    loss_reasons: Mapped[list[str]] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class CallQualityAnalysis(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "call_quality_analyses"
    __table_args__ = (UniqueConstraint("tenant_id", "call_id"),)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    call_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), index=True)
    rule_set_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("call_quality_rule_sets.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    result: Mapped[str | None] = mapped_column(String(30), index=True)
    score: Mapped[int | None] = mapped_column(Integer)
    transcript: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    criteria_scores: Mapped[list[dict] | None] = mapped_column(JSONB)
    loss_reasons: Mapped[list[str] | None] = mapped_column(JSONB)
    recommendations: Mapped[list[str] | None] = mapped_column(JSONB)
    model_version: Mapped[str | None] = mapped_column(String(100))
