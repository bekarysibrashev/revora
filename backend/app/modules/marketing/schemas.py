from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MarketingSourcePerformance(BaseModel):
    source: str
    spend: Decimal
    attributed_revenue: Decimal
    roas: Decimal | None


class MarketingOverviewResponse(BaseModel):
    total_spend: Decimal
    total_attributed_revenue: Decimal
    roas: Decimal | None
    sources: list[MarketingSourcePerformance]
    date_from: date
    date_to: date
    branch_id: UUID | None
    data_as_of: datetime | None


class MetaAdsAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    external_account_id: str
    name: str
    account_status: int
    currency: str
    timezone_name: str
    last_synced_at: datetime | None
    last_error: str | None


class MetaAdsStatusResponse(BaseModel):
    configured: bool
    requested_account_ids: list[str]
    accounts: list[MetaAdsAccountResponse]
    last_synced_at: datetime | None


class MetaAdsSyncResponse(BaseModel):
    status: str
    accounts_synced: int
    rows_received: int
    rows_written: int
    date_from: date
    date_to: date
    synced_at: datetime


class MetaCampaignPerformance(BaseModel):
    account_external_id: str
    account_name: str
    currency: str
    campaign_external_id: str
    campaign_name: str
    spend: Decimal
    impressions: int
    clicks: int
    link_clicks: int
    conversations_started: int
    messaging_connections: int
    ctr: Decimal | None
    cpc: Decimal | None
    cost_per_conversation: Decimal | None


class MetaAdsOverviewResponse(BaseModel):
    total_spend: Decimal
    currency: str | None
    impressions: int
    clicks: int
    conversations_started: int
    ctr: Decimal | None
    cpc: Decimal | None
    cost_per_conversation: Decimal | None
    campaigns: list[MetaCampaignPerformance]
    date_from: date
    date_to: date
    data_as_of: datetime | None
