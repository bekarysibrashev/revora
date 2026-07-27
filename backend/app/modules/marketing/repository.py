from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.models import RevenueFact
from app.modules.marketing.meta_client import MetaAccountData, MetaCampaignDay
from app.modules.marketing.models import (
    AttributionFact,
    MarketingSpendFact,
    MetaAdsAccount,
    MetaCampaignDailyMetric,
)


@dataclass(frozen=True)
class MarketingTotals:
    spend_by_source: dict[str, Decimal]
    revenue_by_source: dict[str, Decimal]
    data_as_of: datetime | None


@dataclass(frozen=True)
class MetaCampaignTotals:
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


class MarketingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def overview(
        self, tenant_id: UUID, date_from: date, date_to: date, branch_id: UUID | None
    ) -> MarketingTotals:
        spend_statement = (
            select(
                MarketingSpendFact.source,
                func.sum(MarketingSpendFact.amount),
                func.max(MarketingSpendFact.updated_at),
            )
            .where(
                MarketingSpendFact.tenant_id == tenant_id,
                MarketingSpendFact.spend_date >= date_from,
                MarketingSpendFact.spend_date <= date_to,
            )
            .group_by(MarketingSpendFact.source)
        )
        if branch_id:
            spend_statement = spend_statement.where(MarketingSpendFact.branch_id == branch_id)
        spend_rows = (await self.session.execute(spend_statement)).all()

        revenue_statement = (
            select(
                AttributionFact.source,
                func.sum(AttributionFact.attributed_amount),
                func.max(AttributionFact.updated_at),
            )
            .join(RevenueFact, RevenueFact.id == AttributionFact.revenue_fact_id)
            .where(
                AttributionFact.tenant_id == tenant_id,
                RevenueFact.occurred_at >= self._start(date_from),
                RevenueFact.occurred_at < self._end(date_to),
            )
            .group_by(AttributionFact.source)
        )
        if branch_id:
            revenue_statement = revenue_statement.where(RevenueFact.branch_id == branch_id)
        revenue_rows = (await self.session.execute(revenue_statement)).all()
        timestamps = [row[2] for row in [*spend_rows, *revenue_rows] if row[2]]
        return MarketingTotals(
            spend_by_source={row[0]: Decimal(row[1]) for row in spend_rows},
            revenue_by_source={row[0]: Decimal(row[1]) for row in revenue_rows},
            data_as_of=max(timestamps) if timestamps else None,
        )

    async def upsert_meta_account(
        self, tenant_id: UUID, data: MetaAccountData, synced_at: datetime
    ) -> MetaAdsAccount:
        statement = insert(MetaAdsAccount).values(
            tenant_id=tenant_id,
            external_account_id=data.external_account_id,
            name=data.name,
            account_status=data.account_status,
            currency=data.currency,
            timezone_name=data.timezone_name,
            last_synced_at=synced_at,
            last_error=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["tenant_id", "external_account_id"],
            set_={
                "name": statement.excluded.name,
                "account_status": statement.excluded.account_status,
                "currency": statement.excluded.currency,
                "timezone_name": statement.excluded.timezone_name,
                "last_synced_at": statement.excluded.last_synced_at,
                "last_error": None,
                "updated_at": func.now(),
            },
        ).returning(MetaAdsAccount)
        return (await self.session.scalars(statement)).one()

    async def upsert_meta_campaign_days(
        self,
        tenant_id: UUID,
        account_id: UUID,
        rows: list[MetaCampaignDay],
    ) -> int:
        if not rows:
            return 0
        values = [
            {
                "tenant_id": tenant_id,
                "account_id": account_id,
                "campaign_external_id": row.campaign_external_id,
                "campaign_name": row.campaign_name,
                "metric_date": row.metric_date,
                "spend": row.spend,
                "impressions": row.impressions,
                "reach": row.reach,
                "clicks": row.clicks,
                "link_clicks": row.link_clicks,
                "conversations_started": row.conversations_started,
                "messaging_connections": row.messaging_connections,
                "actions": row.actions,
            }
            for row in rows
        ]
        statement = insert(MetaCampaignDailyMetric).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=[
                "tenant_id",
                "account_id",
                "campaign_external_id",
                "metric_date",
            ],
            set_={
                "campaign_name": statement.excluded.campaign_name,
                "spend": statement.excluded.spend,
                "impressions": statement.excluded.impressions,
                "reach": statement.excluded.reach,
                "clicks": statement.excluded.clicks,
                "link_clicks": statement.excluded.link_clicks,
                "conversations_started": statement.excluded.conversations_started,
                "messaging_connections": statement.excluded.messaging_connections,
                "actions": statement.excluded.actions,
                "updated_at": func.now(),
            },
        )
        await self.session.execute(statement)
        return len(rows)

    async def list_meta_accounts(self, tenant_id: UUID) -> list[MetaAdsAccount]:
        return list(
            (
                await self.session.scalars(
                    select(MetaAdsAccount)
                    .where(MetaAdsAccount.tenant_id == tenant_id)
                    .order_by(MetaAdsAccount.name)
                )
            ).all()
        )

    async def meta_campaign_totals(
        self, tenant_id: UUID, date_from: date, date_to: date
    ) -> list[MetaCampaignTotals]:
        rows = (
            await self.session.execute(
                select(
                    MetaAdsAccount.external_account_id,
                    MetaAdsAccount.name,
                    MetaAdsAccount.currency,
                    MetaCampaignDailyMetric.campaign_external_id,
                    MetaCampaignDailyMetric.campaign_name,
                    func.sum(MetaCampaignDailyMetric.spend),
                    func.sum(MetaCampaignDailyMetric.impressions),
                    func.sum(MetaCampaignDailyMetric.clicks),
                    func.sum(MetaCampaignDailyMetric.link_clicks),
                    func.sum(MetaCampaignDailyMetric.conversations_started),
                    func.sum(MetaCampaignDailyMetric.messaging_connections),
                )
                .join(
                    MetaAdsAccount,
                    MetaAdsAccount.id == MetaCampaignDailyMetric.account_id,
                )
                .where(
                    MetaCampaignDailyMetric.tenant_id == tenant_id,
                    MetaCampaignDailyMetric.metric_date >= date_from,
                    MetaCampaignDailyMetric.metric_date <= date_to,
                )
                .group_by(
                    MetaAdsAccount.external_account_id,
                    MetaAdsAccount.name,
                    MetaAdsAccount.currency,
                    MetaCampaignDailyMetric.campaign_external_id,
                    MetaCampaignDailyMetric.campaign_name,
                )
                .order_by(func.sum(MetaCampaignDailyMetric.spend).desc())
            )
        ).all()
        return [
            MetaCampaignTotals(
                account_external_id=row[0],
                account_name=row[1],
                currency=row[2],
                campaign_external_id=row[3],
                campaign_name=row[4],
                spend=Decimal(row[5] or 0),
                impressions=int(row[6] or 0),
                clicks=int(row[7] or 0),
                link_clicks=int(row[8] or 0),
                conversations_started=int(row[9] or 0),
                messaging_connections=int(row[10] or 0),
            )
            for row in rows
        ]

    @staticmethod
    def _start(value: date) -> datetime:
        return datetime.combine(value, time.min, tzinfo=timezone.utc)

    @staticmethod
    def _end(value: date) -> datetime:
        return datetime.combine(value + timedelta(days=1), time.min, tzinfo=timezone.utc)
