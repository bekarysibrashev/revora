from datetime import UTC, date, datetime
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
    MetaAdsOverviewResponse,
    MetaAdsStatusResponse,
    MetaAdsSyncResponse,
    MetaCampaignPerformance,
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
        try:
            for account_id in self.meta_account_ids:
                account_data = await self.meta_client.account(account_id)
                account = await self.repository.upsert_meta_account(
                    user.tenant_id, account_data, synced_at
                )
                rows = await self.meta_client.campaign_days(
                    account_id, date_from, date_to
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
        self, user: User, date_from: date, date_to: date
    ) -> MetaAdsOverviewResponse:
        self._require_marketing_role(user)
        self._validate_dates(date_from, date_to, maximum_days=366)
        rows = await self.repository.meta_campaign_totals(
            user.tenant_id, date_from, date_to
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
                link_clicks=row.link_clicks,
                conversations_started=row.conversations_started,
                messaging_connections=row.messaging_connections,
                ctr=self._ratio(row.clicks, row.impressions),
                cpc=self._ratio(row.spend, row.clicks),
                cost_per_conversation=self._ratio(
                    row.spend, row.conversations_started
                ),
            )
            for row in rows
        ]
        total_spend = sum((row.spend for row in rows), Decimal("0"))
        impressions = sum(row.impressions for row in rows)
        clicks = sum(row.clicks for row in rows)
        conversations = sum(row.conversations_started for row in rows)
        accounts = await self.repository.list_meta_accounts(user.tenant_id)
        timestamps = [item.last_synced_at for item in accounts if item.last_synced_at]
        return MetaAdsOverviewResponse(
            total_spend=total_spend,
            currency=next(iter(currencies)) if currencies else None,
            impressions=impressions,
            clicks=clicks,
            conversations_started=conversations,
            ctr=self._ratio(clicks, impressions),
            cpc=self._ratio(total_spend, clicks),
            cost_per_conversation=self._ratio(total_spend, conversations),
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
