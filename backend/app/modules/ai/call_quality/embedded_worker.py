"""Small durable call worker for single-process deployments without Celery.

Queued work remains in PostgreSQL, so a Render restart cannot lose it. This
worker is intentionally sequential to keep free/small instances stable. Larger
installations disable it and use the existing Celery worker and beat services.
"""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
import logging

from sqlalchemy import select, text, update

from app.core.config import Settings
from app.core.database import AsyncSessionFactory
from app.modules.ai.call_quality.models import CallQualityAnalysis
from app.modules.ai.call_quality.pipeline import CallQualityPipeline, RUNNABLE_STATUSES
from app.modules.tenancy.models import Tenant


logger = logging.getLogger(__name__)


class EmbeddedCallWorker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self.settings.embedded_call_worker or self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="revora-call-worker")
        logger.info("Embedded call worker started")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("Embedded call worker stopped")

    async def _loop(self) -> None:
        await asyncio.sleep(2)
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Embedded call worker iteration failed")
            await asyncio.sleep(self.settings.embedded_call_worker_interval_seconds)

    async def run_once(self) -> bool:
        """Process at most one analysis and return whether work was found."""
        async with AsyncSessionFactory() as session:
            tenant_ids = list((await session.scalars(
                select(Tenant.id).where(Tenant.is_active.is_(True))
            )).all())
            for tenant_id in tenant_ids:
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                    {"tenant_id": str(tenant_id)},
                )
                stale_before = datetime.now(UTC) - timedelta(
                    minutes=self.settings.embedded_call_processing_timeout_minutes
                )
                await session.execute(
                    update(CallQualityAnalysis)
                    .where(
                        CallQualityAnalysis.tenant_id == tenant_id,
                        CallQualityAnalysis.status == "processing",
                        CallQualityAnalysis.processing_started_at < stale_before,
                    )
                    .values(
                        status="retrying",
                        error_code="WORKER_INTERRUPTED",
                        error_message="Analysis resumed after an interrupted worker",
                    )
                )
                analysis_id = await session.scalar(
                    select(CallQualityAnalysis.id)
                    .where(
                        CallQualityAnalysis.tenant_id == tenant_id,
                        CallQualityAnalysis.status.in_(RUNNABLE_STATUSES),
                    )
                    .order_by(
                        CallQualityAnalysis.queued_at.asc().nullsfirst(),
                        CallQualityAnalysis.created_at.asc(),
                    )
                    .limit(1)
                )
                await session.commit()
                if analysis_id is None:
                    continue
                retry = await CallQualityPipeline(session, self.settings).run(
                    tenant_id, analysis_id
                )
                # The durable status is enough: retrying rows are picked up on
                # the next loop with the same bounded attempt policy.
                logger.info(
                    "Embedded call analysis handled tenant=%s analysis=%s retry=%s",
                    tenant_id,
                    analysis_id,
                    retry,
                )
                return True
        return False
