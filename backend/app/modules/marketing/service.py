from datetime import date
from decimal import Decimal
from uuid import UUID

from app.core.errors import AppError
from app.modules.auth.models import User, UserRole
from app.modules.marketing.repository import MarketingRepository
from app.modules.marketing.schemas import MarketingOverviewResponse, MarketingSourcePerformance


class MarketingService:
    def __init__(self, repository: MarketingRepository) -> None:
        self.repository = repository

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
