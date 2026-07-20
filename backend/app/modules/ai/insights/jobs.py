"""Celery entry point for periodic V1 insight recalculation."""
import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionFactory
from app.modules.ai.insights.generator import InsightGenerator
from app.modules.tenancy.models import Tenant
from app.worker import celery_app

@celery_app.task(name="revora.generate_insights")
def generate_insights() -> dict[str, int]:
    return asyncio.run(_generate())

async def _generate() -> dict[str, int]:
    tenants_processed = insights_written = 0
    async with AsyncSessionFactory() as session:
        tenant_ids = list((await session.scalars(select(Tenant.id).where(Tenant.is_active.is_(True)))).all())
        for tenant_id in tenant_ids:
            insights_written += await InsightGenerator(session).generate_for_tenant(tenant_id)
            await session.commit()
            tenants_processed += 1
    return {"tenants_processed": tenants_processed, "insights_written": insights_written}
