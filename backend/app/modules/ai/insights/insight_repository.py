from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.models import AIInsight, AIInsightRead


class InsightRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_visible(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        branch_ids: list[UUID] | None,
        severity: str | None,
        insight_type: str | None,
    ) -> list[AIInsight]:
        statement = (
            select(AIInsight)
            .outerjoin(
                AIInsightRead,
                (AIInsightRead.insight_id == AIInsight.id)
                & (AIInsightRead.user_id == user_id),
            )
            .where(
                AIInsight.tenant_id == tenant_id,
                or_(AIInsight.valid_until.is_(None), AIInsight.valid_until > datetime.now(UTC)),
                AIInsightRead.dismissed_at.is_(None),
            )
            .order_by(AIInsight.detected_at.desc())
            .limit(100)
        )
        if branch_ids is not None:
            statement = statement.where(
                or_(AIInsight.branch_id.is_(None), AIInsight.branch_id.in_(branch_ids))
            )
        if severity:
            statement = statement.where(AIInsight.severity == severity)
        if insight_type:
            statement = statement.where(AIInsight.insight_type == insight_type)
        return list((await self.session.scalars(statement)).all())

    async def get(self, tenant_id: UUID, insight_id: UUID) -> AIInsight | None:
        return await self.session.scalar(
            select(AIInsight).where(
                AIInsight.tenant_id == tenant_id, AIInsight.id == insight_id
            )
        )

    async def dismiss(self, insight_id: UUID, user_id: UUID) -> None:
        statement = insert(AIInsightRead).values(
            insight_id=insight_id,
            user_id=user_id,
            dismissed_at=datetime.now(UTC),
        )
        statement = statement.on_conflict_do_update(
            index_elements=["insight_id", "user_id"],
            set_={"dismissed_at": statement.excluded.dismissed_at},
        )
        await self.session.execute(statement)
