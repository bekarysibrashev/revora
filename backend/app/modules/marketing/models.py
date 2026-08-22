"""Marketing spend and cross-channel attribution facts."""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
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


class MetaAdsAccount(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "meta_ads_accounts"
    __table_args__ = (UniqueConstraint("tenant_id", "external_account_id"),)

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    external_account_id: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(250))
    account_status: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    timezone_name: Mapped[str] = mapped_column(String(100))
    last_sync_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class MetaCampaignDailyMetric(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "meta_campaign_daily_metrics"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "account_id", "campaign_external_id", "metric_date"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("meta_ads_accounts.id", ondelete="CASCADE"),
        index=True,
    )
    campaign_external_id: Mapped[str] = mapped_column(String(80), index=True)
    campaign_name: Mapped[str] = mapped_column(String(250))
    status: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    effective_status: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    metric_date: Mapped[date] = mapped_column(Date, index=True)
    spend: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    impressions: Mapped[int] = mapped_column(Integer)
    reach: Mapped[int] = mapped_column(Integer)
    clicks: Mapped[int] = mapped_column(Integer)
    unique_clicks: Mapped[int] = mapped_column(Integer, default=0)
    link_clicks: Mapped[int] = mapped_column(Integer)
    outbound_clicks: Mapped[int] = mapped_column(Integer, default=0)
    landing_page_views: Mapped[int] = mapped_column(Integer, default=0)
    leads: Mapped[int] = mapped_column(Integer, default=0)
    purchases: Mapped[int] = mapped_column(Integer, default=0)
    conversations_started: Mapped[int] = mapped_column(Integer)
    messaging_connections: Mapped[int] = mapped_column(Integer)
    video_plays: Mapped[int] = mapped_column(Integer, default=0)
    video_thruplays: Mapped[int] = mapped_column(Integer, default=0)
    actions: Mapped[list] = mapped_column(JSONB, default=list)
    action_values: Mapped[list] = mapped_column(JSONB, default=list)
    outbound_clicks_raw: Mapped[list] = mapped_column(JSONB, default=list)
