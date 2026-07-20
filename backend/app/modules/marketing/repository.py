from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.models import RevenueFact
from app.modules.marketing.models import AttributionFact, MarketingSpendFact


@dataclass(frozen=True)
class MarketingTotals:
    spend_by_source: dict[str, Decimal]
    revenue_by_source: dict[str, Decimal]
    data_as_of: datetime | None


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

    @staticmethod
    def _start(value: date) -> datetime:
        return datetime.combine(value, time.min, tzinfo=timezone.utc)

    @staticmethod
    def _end(value: date) -> datetime:
        return datetime.combine(value + timedelta(days=1), time.min, tzinfo=timezone.utc)
