"""Marketing spend and cross-channel attribution facts."""
from datetime import date
from decimal import Decimal
from uuid import UUID
from sqlalchemy import Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

class MarketingSpendFact(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "marketing_spend_facts"
    __table_args__ = (UniqueConstraint("tenant_id", "source", "external_id", "spend_date"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("branches.id"))
    source: Mapped[str] = mapped_column(String(50)); external_id: Mapped[str] = mapped_column(String(150))
    campaign_name: Mapped[str | None] = mapped_column(String(250)); spend_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2)); currency: Mapped[str] = mapped_column(String(3), default="KZT")

class AttributionFact(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "attribution_facts"
    __table_args__ = (UniqueConstraint("tenant_id", "lead_id", "revenue_fact_id"),)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    lead_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    revenue_fact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("revenue_facts.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(50)); confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    attributed_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2)); currency: Mapped[str] = mapped_column(String(3), default="KZT")
