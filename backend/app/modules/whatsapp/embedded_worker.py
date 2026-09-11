"""Periodic Google Sheet -> knowledge base resync for single-process deployments.

Revora has no separate Celery worker/beat service running in production (see
app/modules/ai/call_quality/embedded_worker.py for the same reasoning), so
"sync on a schedule" for a connected knowledge sheet has to happen inside the
existing web process instead. This mirrors that file's shape: a small
asyncio loop started from the FastAPI lifespan, looping over tenants under
their own row-level-security context, skipping any tenant with no sheet
connected (or sync disabled) -- a near-instant no-op for everyone else.
"""

import asyncio
from contextlib import suppress
import logging

from sqlalchemy import select, text

from app.core.config import Settings
from app.core.database import AsyncSessionFactory
from app.modules.tenancy.models import Tenant
from app.modules.whatsapp.models import WhatsAppKnowledgeSheet
from app.modules.whatsapp.service import WhatsAppService


logger = logging.getLogger(__name__)


class EmbeddedKnowledgeSheetWorker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self.settings.embedded_knowledge_sheet_worker or self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="revora-knowledge-sheet-worker")
        logger.info("Embedded WhatsApp knowledge-sheet sync worker started")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("Embedded WhatsApp knowledge-sheet sync worker stopped")

    async def _loop(self) -> None:
        await asyncio.sleep(15)
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Embedded knowledge-sheet worker iteration failed")
            await asyncio.sleep(self.settings.embedded_knowledge_sheet_worker_interval_seconds)

    async def run_once(self) -> int:
        """Resync every tenant's connected, enabled sheet. Returns how many ran."""
        synced = 0
        async with AsyncSessionFactory() as session:
            tenant_ids = list(
                (await session.scalars(select(Tenant.id).where(Tenant.is_active.is_(True)))).all()
            )
            service = WhatsAppService(session, self.settings)
            for tenant_id in tenant_ids:
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                    {"tenant_id": str(tenant_id)},
                )
                sheet = await session.scalar(
                    select(WhatsAppKnowledgeSheet).where(
                        WhatsAppKnowledgeSheet.tenant_id == tenant_id,
                        WhatsAppKnowledgeSheet.is_enabled.is_(True),
                    )
                )
                if sheet is None:
                    continue
                # Scheduled runs have no owner behind them, so freshly
                # auto-approved rows are attributed to nobody -- the owner
                # still sees the outcome (counts + timestamp) on the page.
                await service._run_sheet_sync(sheet, approved_by_id=None)
                await session.commit()
                synced += 1
                logger.info(
                    "Knowledge sheet resynced tenant=%s status=%s",
                    tenant_id,
                    sheet.last_sync_status,
                )
        return synced
