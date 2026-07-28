"""Celery tasks for automatic analysis of every eligible completed call."""
import asyncio
from uuid import UUID

from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.database import AsyncSessionFactory
from app.modules.ai.call_quality.models import CallQualityAnalysis
from app.modules.ai.call_quality.pipeline import CallQualityPipeline
from app.modules.tenancy.models import Tenant
from app.worker import celery_app


@celery_app.task(bind=True, name="revora.process_call_analysis", max_retries=9)
def process_call_analysis(self, tenant_id: str, analysis_id: str) -> dict[str, str]:
    retry = asyncio.run(_process(UUID(tenant_id), UUID(analysis_id)))
    if retry:
        countdown = min(60 * (2 ** self.request.retries), 900)
        raise self.retry(countdown=countdown)
    return {"analysis_id": analysis_id, "status": "handled"}


async def _process(tenant_id: UUID, analysis_id: UUID) -> bool:
    async with AsyncSessionFactory() as session:
        return await CallQualityPipeline(session, get_settings()).run(tenant_id, analysis_id)


@celery_app.task(name="revora.enqueue_pending_call_analyses")
def enqueue_pending_call_analyses() -> dict[str, int]:
    return asyncio.run(_enqueue_pending())


async def _enqueue_pending() -> dict[str, int]:
    enqueued = 0
    async with AsyncSessionFactory() as session:
        tenant_ids = list(
            (await session.scalars(select(Tenant.id).where(Tenant.is_active.is_(True)))).all()
        )
        for tenant_id in tenant_ids:
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )
            ids = list(
                (await session.scalars(
                    select(CallQualityAnalysis.id).where(
                        CallQualityAnalysis.tenant_id == tenant_id,
                        CallQualityAnalysis.status.in_(("pending", "queued", "retrying")),
                    ).limit(200)
                )).all()
            )
            await session.commit()
            for analysis_id in ids:
                process_call_analysis.delay(str(tenant_id), str(analysis_id))
                enqueued += 1
    return {"enqueued": enqueued}
