from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.marketing.repository import MarketingRepository
from app.modules.marketing.meta_client import MetaAdsClient, MetaAdsError
from app.modules.marketing.schemas import (
    MarketingOverviewResponse,
    MarketingSourcePerformance,
    MetaAdsAccountResponse,
    MetaAccountPerformance,
    MetaAdsOverviewResponse,
    MetaAdsStatusResponse,
    MetaAdsSyncResponse,
    MetaCampaignAlert,
    MetaCampaignPerformance,
    MetaPeriodComparison,
)


class MarketingService:
    def __init__(
        self,
        repository: MarketingRepository,
        meta_client: MetaAdsClient | None = None,
        meta_account_ids: list[str] | None = None,
    ) -> None:
        self.repository = repository
        self.meta_client = meta_client
        self.meta_account_ids = meta_account_ids or []

    async def overview(
        self, user: User, date_from: date, date_to: date, branch_id: UUID | None
    ) -> MarketingOverviewResponse:
        if user.role not in {UserRole.OWNER, UserRole.MANAGER}:
            raise AppError("FORBIDDEN", "Marketing analytics are not available for this role", 403)
        if date_from > date_to:
            raise AppError("INVALID_DATE_RANGE", "date_from must not be after date_to", 422)
        allowed = {link.branch_id for link in user.branch_links}
        if branch_id and allowed and branch_id not in allowed:
            raise AppError("BRANCH_FORBIDDEN", "Branch is outside your access scope", 403)
        totals = await self.repository.overview(user.tenant_id, date_from, date_to, branch_id)
        sources = sorted(set(totals.spend_by_source) | set(totals.revenue_by_source))
        items = []
        for source in sources:
            spend = totals.spend_by_source.get(source, Decimal("0"))
            revenue = totals.revenue_by_source.get(source, Decimal("0"))
            items.append(
                MarketingSourcePerformance(
                    source=source,
                    spend=spend,
                    attributed_revenue=revenue,
                    roas=revenue / spend if spend else None,
                )
            )
        total_spend = sum((item.spend for item in items), Decimal("0"))
        total_revenue = sum((item.attributed_revenue for item in items), Decimal("0"))
        return MarketingOverviewResponse(
            total_spend=total_spend,
            total_attributed_revenue=total_revenue,
            roas=total_revenue / total_spend if total_spend else None,
            sources=items,
            date_from=date_from,
            date_to=date_to,
            branch_id=branch_id,
            data_as_of=totals.data_as_of,
        )

    async def meta_status(self, user: User) -> MetaAdsStatusResponse:
        self._require_marketing_role(user)
        accounts = await self.repository.list_meta_accounts(user.tenant_id)
        timestamps = [item.last_synced_at for item in accounts if item.last_synced_at]
        return MetaAdsStatusResponse(
            configured=self.meta_client is not None and bool(self.meta_account_ids),
            requested_account_ids=self.meta_account_ids,
            accounts=[MetaAdsAccountResponse.model_validate(item) for item in accounts],
            last_synced_at=max(timestamps) if timestamps else None,
        )

    async def sync_meta(
        self, user: User, date_from: date, date_to: date
    ) -> MetaAdsSyncResponse:
        if user.role != UserRole.OWNER:
            raise AppError("FORBIDDEN", "Only the owner can synchronize Meta Ads", 403)
        self._validate_dates(date_from, date_to, maximum_days=90)
        if self.meta_client is None or not self.meta_account_ids:
            raise AppError(
                "META_NOT_CONFIGURED",
                "Meta Ads secrets are not configured on the backend",
                503,
            )

        synced_at = datetime.now(UTC)
        rows_received = 0
        rows_written = 0
        period_days = (date_to - date_from).days + 1
        comparison_date_from = date_from - timedelta(days=period_days)
        try:
            for account_id in self.meta_account_ids:
                account_data = await self.meta_client.account(account_id)
                account = await self.repository.upsert_meta_account(
                    user.tenant_id, account_data, synced_at
                )
                rows = await self.meta_client.campaign_days(
                    account_id, comparison_date_from, date_to
                )
                rows_received += len(rows)
                rows_written += await self.repository.upsert_meta_campaign_days(
                    user.tenant_id, account.id, rows
                )
        except MetaAdsError as exc:
            raise AppError("META_SYNC_FAILED", str(exc), 502) from exc

        return MetaAdsSyncResponse(
            status="completed",
            accounts_synced=len(self.meta_account_ids),
            rows_received=rows_received,
            rows_written=rows_written,
            date_from=date_from,
            date_to=date_to,
            synced_at=synced_at,
        )

    async def meta_overview(
        self,
        user: User,
        date_from: date,
        date_to: date,
        account_id: str | None = None,
    ) -> MetaAdsOverviewResponse:
        self._require_marketing_role(user)
        self._validate_dates(date_from, date_to, maximum_days=366)
        all_rows = await self.repository.meta_campaign_totals(
            user.tenant_id, date_from, date_to, None
        )
        accounts = await self.repository.list_meta_accounts(user.tenant_id)
        known_accounts = {item.external_account_id for item in accounts}
        if account_id and account_id not in known_accounts:
            raise AppError(
                "META_ACCOUNT_NOT_FOUND",
                "The selected Meta Ads account has no data in this tenant",
                404,
            )
        rows = (
            [row for row in all_rows if row.account_external_id == account_id]
            if account_id
            else all_rows
        )
        period_days = (date_to - date_from).days + 1
        previous_date_to = date_from - timedelta(days=1)
        previous_date_from = previous_date_to - timedelta(days=period_days - 1)
        all_previous_rows = await self.repository.meta_campaign_totals(
            user.tenant_id, previous_date_from, previous_date_to, None
        )
        previous_rows = (
            [
                row
                for row in all_previous_rows
                if row.account_external_id == account_id
            ]
            if account_id
            else all_previous_rows
        )
        currencies = {row.currency for row in rows}
        if len(currencies) > 1:
            raise AppError(
                "META_MIXED_CURRENCIES",
                "Meta accounts use different currencies and cannot be summed",
                409,
            )
        campaigns = [
            MetaCampaignPerformance(
                account_external_id=row.account_external_id,
                account_name=row.account_name,
                currency=row.currency,
                campaign_external_id=row.campaign_external_id,
                campaign_name=row.campaign_name,
                spend=row.spend,
                impressions=row.impressions,
                clicks=row.clicks,
                unique_clicks=row.unique_clicks,
                link_clicks=row.link_clicks,
                outbound_clicks=row.outbound_clicks,
                landing_page_views=row.landing_page_views,
                leads=row.leads,
                purchases=row.purchases,
                conversations_started=row.conversations_started,
                messaging_connections=row.messaging_connections,
                video_plays=row.video_plays,
                video_thruplays=row.video_thruplays,
                ctr=self._ratio(row.clicks, row.impressions),
                cpc=self._ratio(row.spend, row.clicks),
                cpm=self._ratio(row.spend * 1000, row.impressions),
                cost_per_lead=self._ratio(row.spend, row.leads),
                cost_per_conversation=self._ratio(
                    row.spend, row.conversations_started
                ),
                click_to_conversation_rate=self._ratio(
                    row.conversations_started, row.link_clicks
                ),
                landing_page_view_rate=self._ratio(
                    row.landing_page_views, row.outbound_clicks
                ),
                video_thruplay_rate=self._ratio(
                    row.video_thruplays, row.video_plays
                ),
            )
            for row in rows
        ]
        total_spend = sum((row.spend for row in rows), Decimal("0"))
        impressions = sum(row.impressions for row in rows)
        clicks = sum(row.clicks for row in rows)
        unique_clicks = sum(row.unique_clicks for row in rows)
        link_clicks = sum(row.link_clicks for row in rows)
        outbound_clicks = sum(row.outbound_clicks for row in rows)
        landing_page_views = sum(row.landing_page_views for row in rows)
        leads = sum(row.leads for row in rows)
        purchases = sum(row.purchases for row in rows)
        conversations = sum(row.conversations_started for row in rows)
        messaging_connections = sum(row.messaging_connections for row in rows)
        video_plays = sum(row.video_plays for row in rows)
        video_thruplays = sum(row.video_thruplays for row in rows)
        previous_spend = sum(
            (row.spend for row in previous_rows), Decimal("0")
        )
        previous_conversations = sum(
            row.conversations_started for row in previous_rows
        )
        previous_leads = sum(row.leads for row in previous_rows)
        previous_cost_per_conversation = self._ratio(
            previous_spend, previous_conversations
        )
        cost_per_conversation = self._ratio(total_spend, conversations)
        account_groups: dict[str, list] = {}
        for row in all_rows:
            account_groups.setdefault(row.account_external_id, []).append(row)
        account_performance = []
        for external_id, account_rows in account_groups.items():
            account_spend = sum((row.spend for row in account_rows), Decimal("0"))
            account_impressions = sum(row.impressions for row in account_rows)
            account_clicks = sum(row.clicks for row in account_rows)
            account_conversations = sum(
                row.conversations_started for row in account_rows
            )
            account_performance.append(
                MetaAccountPerformance(
                    account_external_id=external_id,
                    account_name=account_rows[0].account_name,
                    currency=account_rows[0].currency,
                    spend=account_spend,
                    impressions=account_impressions,
                    clicks=account_clicks,
                    conversations_started=account_conversations,
                    leads=sum(row.leads for row in account_rows),
                    ctr=self._ratio(account_clicks, account_impressions),
                    cpc=self._ratio(account_spend, account_clicks),
                    cost_per_conversation=self._ratio(
                        account_spend, account_conversations
                    ),
                )
            )
        timestamps = [item.last_synced_at for item in accounts if item.last_synced_at]
        alerts = self._campaign_alerts(
            campaigns, cost_per_conversation
        )
        return MetaAdsOverviewResponse(
            total_spend=total_spend,
            currency=next(iter(currencies)) if currencies else None,
            impressions=impressions,
            clicks=clicks,
            unique_clicks=unique_clicks,
            link_clicks=link_clicks,
            outbound_clicks=outbound_clicks,
            landing_page_views=landing_page_views,
            leads=leads,
            purchases=purchases,
            conversations_started=conversations,
            messaging_connections=messaging_connections,
            video_plays=video_plays,
            video_thruplays=video_thruplays,
            ctr=self._ratio(clicks, impressions),
            cpc=self._ratio(total_spend, clicks),
            cpm=self._ratio(total_spend * 1000, impressions),
            cost_per_lead=self._ratio(total_spend, leads),
            cost_per_conversation=cost_per_conversation,
            click_to_conversation_rate=self._ratio(
                conversations, link_clicks
            ),
            landing_page_view_rate=self._ratio(
                landing_page_views, outbound_clicks
            ),
            video_thruplay_rate=self._ratio(
                video_thruplays, video_plays
            ),
            selected_account_id=account_id,
            comparison=MetaPeriodComparison(
                previous_date_from=previous_date_from,
                previous_date_to=previous_date_to,
                total_spend=previous_spend,
                conversations_started=previous_conversations,
                leads=previous_leads,
                cost_per_conversation=previous_cost_per_conversation,
                spend_change=self._change(total_spend, previous_spend),
                conversations_change=self._change(
                    conversations, previous_conversations
                ),
                leads_change=self._change(leads, previous_leads),
                cost_per_conversation_change=self._change(
                    cost_per_conversation, previous_cost_per_conversation
                ),
            ),
            alerts=alerts,
            accounts=sorted(
                account_performance, key=lambda item: item.spend, reverse=True
            ),
            campaigns=campaigns,
            date_from=date_from,
            date_to=date_to,
            data_as_of=max(timestamps) if timestamps else None,
        )

    @staticmethod
    def _require_marketing_role(user: User) -> None:
        if user.role not in {UserRole.OWNER, UserRole.MANAGER}:
            raise AppError(
                "FORBIDDEN", "Marketing analytics are not available for this role", 403
            )

    @staticmethod
    def _validate_dates(
        date_from: date, date_to: date, *, maximum_days: int
    ) -> None:
        if date_from > date_to:
            raise AppError("INVALID_DATE_RANGE", "date_from must not be after date_to", 422)
        if (date_to - date_from).days + 1 > maximum_days:
            raise AppError(
                "DATE_RANGE_TOO_LARGE",
                f"Date range cannot exceed {maximum_days} days",
                422,
            )

    @staticmethod
    def _ratio(numerator, denominator) -> Decimal | None:
        if not denominator:
            return None
        return Decimal(numerator) / Decimal(denominator)

    @staticmethod
    def _change(current, previous) -> Decimal | None:
        if current is None or previous is None or not previous:
            return None
        return (Decimal(current) - Decimal(previous)) / Decimal(previous)

    @staticmethod
    def _campaign_alerts(
        campaigns: list[MetaCampaignPerformance],
        average_cost_per_conversation: Decimal | None,
    ) -> list[MetaCampaignAlert]:
        alerts: list[MetaCampaignAlert] = []
        for campaign in campaigns:
            common = {
                "account_external_id": campaign.account_external_id,
                "campaign_external_id": campaign.campaign_external_id,
                "campaign_name": campaign.campaign_name,
            }
            if (
                campaign.spend > 0
                and campaign.conversations_started == 0
                and campaign.leads == 0
            ):
                alerts.append(
                    MetaCampaignAlert(
                        severity="critical",
                        code="SPEND_WITHOUT_RESULTS",
                        title="Расход без обращений",
                        description=(
                            f"Кампания потратила {campaign.spend} "
                            f"{campaign.currency}, но Meta не зафиксировала "
                            "ни диалогов, ни лидов."
                        ),
                        **common,
                    )
                )
                continue
            if (
                average_cost_per_conversation
                and campaign.cost_per_conversation
                and campaign.conversations_started >= 3
                and campaign.cost_per_conversation
                > average_cost_per_conversation * Decimal("1.5")
            ):
                alerts.append(
                    MetaCampaignAlert(
                        severity="warning",
                        code="HIGH_CONVERSATION_COST",
                        title="Диалог заметно дороже среднего",
                        description=(
                            "Цена диалога этой кампании более чем на 50% "
                            "выше среднего по выбранному периоду."
                        ),
                        **common,
                    )
                )
            if (
                campaign.outbound_clicks >= 10
                and campaign.landing_page_views == 0
            ):
                alerts.append(
                    MetaCampaignAlert(
                        severity="warning",
                        code="LANDING_TRACKING_GAP",
                        title="Переходы есть, просмотров страницы нет",
                        description=(
                            "Проверьте посадочную страницу и Pixel: Meta "
                            "фиксирует исходящие клики, но не видит загрузку страницы."
                        ),
                        **common,
                    )
                )
        order = {"critical": 0, "warning": 1}
        return sorted(alerts, key=lambda item: order.get(item.severity, 2))
