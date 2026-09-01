"""Durable backend calculation for raw 1C uploads.

The clinic connector only transports validated OData rows. PostgreSQL keeps
the pending queue, so API restarts do not lose calculation work.
"""

import asyncio
from contextlib import suppress
import logging

from sqlalchemy import select, text

from app.core.config import Settings
from app.core.database import AsyncSessionFactory
from app.modules.integrations.canonical_writer import CanonicalWriter
from app.modules.integrations.repository import IntegrationRepository
from app.modules.integrations.service import IntegrationService
from app.modules.tenancy.models import Tenant


logger = logging.getLogger(__name__)


class EmbeddedOneCNormalizationWorker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self.settings.embedded_one_c_worker or self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="revora-one-c-worker")
        logger.info("Embedded 1C normalization worker started")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("Embedded 1C normalization worker stopped")

    async def _loop(self) -> None:
        await asyncio.sleep(2)
        while True:
            found = False
            try:
                found = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Embedded 1C normalization iteration failed")
            await asyncio.sleep(
                0.1 if found else self.settings.embedded_one_c_worker_interval_seconds
            )

    async def run_once(self) -> bool:
        async with AsyncSessionFactory() as session:
            tenant_ids = list(
                (
                    await session.scalars(
                        select(Tenant.id).where(Tenant.is_active.is_(True))
                    )
                ).all()
            )
            for tenant_id in tenant_ids:
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                    {"tenant_id": str(tenant_id)},
                )
                repository = IntegrationRepository(session)
                connections = await repository.queued_one_c_normalization_connections(
                    tenant_id, limit=1
                )
                if not connections:
                    await session.rollback()
                    continue
                connection = connections[0]
                processed_so_far = int(
                    (connection.settings or {}).get("normalization_processed") or 0
                )
                await repository.set_one_c_normalization_state(
                    connection, status="running", processed=processed_so_far
                )
                try:
                    service = IntegrationService(repository, CanonicalWriter(session))
                    processed, normalized, quarantined, remaining = (
                        await service.normalize_one_c_background_batch(
                            tenant_id=tenant_id,
                            connection_id=connection.id,
                            batch_size=self.settings.embedded_one_c_worker_batch_size,
                        )
                    )
                    await repository.set_one_c_normalization_state(
                        connection,
                        status="completed" if remaining == 0 else "running",
                        remaining=remaining,
                        processed=processed_so_far + processed,
                    )
                    await session.commit()
                    logger.info(
                        "1C backend calculation tenant=%s connection=%s processed=%s "
                        "normalized=%s quarantined=%s remaining=%s",
                        tenant_id,
                        connection.id,
                        processed,
                        normalized,
                        quarantined,
                        remaining,
                    )
                    return True
                except Exception as exc:
                    await session.rollback()
                    await session.execute(
                        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                        {"tenant_id": str(tenant_id)},
                    )
                    connection = await repository.get_connection(tenant_id, connection.id)
                    if connection is not None:
                        await repository.set_one_c_normalization_state(
                            connection,
                            status="failed",
                            error=str(exc)[:1000],
                            processed=processed_so_far,
                        )
                        await session.commit()
                    logger.exception(
                        "1C backend calculation failed tenant=%s connection=%s",
                        tenant_id,
                        connection.id if connection else None,
                    )
                    return True
        return False
