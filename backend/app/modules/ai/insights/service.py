from uuid import UUID

from app.core.errors import AppError
from app.modules.ai.insights.insight_repository import InsightRepository
from app.modules.auth.models import User, UserRole
from app.modules.dashboard.schemas import InsightListResponse, InsightResponse


class InsightService:
    def __init__(self, repository: InsightRepository) -> None:
        self.repository = repository

    async def list_insights(
        self,
        user: User,
        *,
        branch_id: UUID | None,
        severity: str | None,
        insight_type: str | None,
    ) -> InsightListResponse:
        branch_ids = self._scope(user, branch_id)
        records = await self.repository.list_visible(
            tenant_id=user.tenant_id,
            user_id=user.id,
            branch_ids=branch_ids,
            severity=severity,
            insight_type=insight_type,
        )
        items = [
            InsightResponse(
                id=item.id,
                branch_id=item.branch_id,
                insight_type=item.insight_type,
                severity=item.severity,
                title=item.title,
                description=item.description,
                evidence=item.evidence,
                detected_at=item.detected_at,
                valid_until=item.valid_until,
            )
            for item in records
        ]
        return InsightListResponse(items=items, total=len(items))

    async def dismiss(self, user: User, insight_id: UUID) -> None:
        self._scope(user, None)
        insight = await self.repository.get(user.tenant_id, insight_id)
        if insight is None:
            raise AppError("INSIGHT_NOT_FOUND", "Insight not found", 404)
        allowed = {link.branch_id for link in user.branch_links}
        if user.role == UserRole.ADMINISTRATOR and insight.branch_id not in allowed | {None}:
            raise AppError("FORBIDDEN", "Insight is outside your branch scope", 403)
        await self.repository.dismiss(insight_id, user.id)

    @staticmethod
    def _scope(user: User, branch_id: UUID | None) -> list[UUID] | None:
        if user.role == UserRole.SALES_MANAGER:
            raise AppError("FORBIDDEN", "Insights are not available for this role", 403)
        allowed = [link.branch_id for link in user.branch_links]
        if branch_id:
            if allowed and branch_id not in allowed:
                raise AppError("BRANCH_FORBIDDEN", "Branch is outside your access scope", 403)
            return [branch_id]
        return allowed if user.role == UserRole.ADMINISTRATOR else None
