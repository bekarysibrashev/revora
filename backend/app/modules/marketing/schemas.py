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
    unique_clicks: int
    link_clicks: int
    outbound_clicks: int
    landing_page_views: int
    leads: int
    purchases: int
    conversations_started: int
    messaging_connections: int
    video_plays: int
    video_thruplays: int
    ctr: Decimal | None
    cpc: Decimal | None
    cpm: Decimal | None
    cost_per_lead: Decimal | None
    cost_per_conversation: Decimal | None
    click_to_conversation_rate: Decimal | None
    landing_page_view_rate: Decimal | None
    video_thruplay_rate: Decimal | None


class MetaAccountPerformance(BaseModel):
    account_external_id: str
    account_name: str
    currency: str
    spend: Decimal
    impressions: int
    clicks: int
    conversations_started: int
    leads: int
    ctr: Decimal | None
    cpc: Decimal | None
    cost_per_conversation: Decimal | None


class MetaPeriodComparison(BaseModel):
    previous_date_from: date
    previous_date_to: date
    total_spend: Decimal
    conversations_started: int
    leads: int
    cost_per_conversation: Decimal | None
    spend_change: Decimal | None
    conversations_change: Decimal | None
    leads_change: Decimal | None
    cost_per_conversation_change: Decimal | None


class MetaCampaignAlert(BaseModel):
    severity: str
    code: str
    account_external_id: str
    campaign_external_id: str
    campaign_name: str
    title: str
    description: str


class MetaBudgetRecommendation(BaseModel):
    rank: int
    action: str
    account_external_id: str
    campaign_external_id: str
    campaign_name: str
    score: int
    result_metric: str
    results: int
    cost_per_result: Decimal | None
    suggested_budget_change_percent: int
    reason: str


class MetaAdsOverviewResponse(BaseModel):
    total_spend: Decimal
    currency: str | None
    impressions: int
    clicks: int
    unique_clicks: int
    link_clicks: int
    outbound_clicks: int
    landing_page_views: int
    leads: int
    purchases: int
    conversations_started: int
    messaging_connections: int
    video_plays: int
    video_thruplays: int
    ctr: Decimal | None
    cpc: Decimal | None
    cpm: Decimal | None
    cost_per_lead: Decimal | None
    cost_per_conversation: Decimal | None
    click_to_conversation_rate: Decimal | None
    landing_page_view_rate: Decimal | None
    video_thruplay_rate: Decimal | None
    selected_account_id: str | None
    comparison: MetaPeriodComparison
    alerts: list[MetaCampaignAlert]
    recommendations: list[MetaBudgetRecommendation]
    accounts: list[MetaAccountPerformance]
    campaigns: list[MetaCampaignPerformance]
    date_from: date
    date_to: date
    data_as_of: datetime | None
