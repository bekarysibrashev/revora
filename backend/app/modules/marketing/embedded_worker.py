"""Periodic Meta Ads synchronization for single-process deployments."""

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from app.core.config import Settings
from app.core.database import AsyncSessionFactory
from app.modules.marketing.meta_client import MetaAdsClient
from app.modules.marketing.repository import MarketingRepository
from app.modules.marketing.service import MarketingService
from app.modules.tenancy.models import Tenant


logger = logging.getLogger(__name__)


class EmbeddedMetaSyncWorker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if (
            not self.settings.meta_auto_sync_enabled
            or not self.settings.meta_access_token.get_secret_value()
            or not self.settings.meta_ad_account_ids
            or self._task is not None
        ):
            return
        self._task = asyncio.create_task(self._loop(), name="revora-meta-sync-worker")
        logger.info("Embedded Meta Ads sync worker started")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("Embedded Meta Ads sync worker stopped")

    async def _loop(self) -> None:
        await asyncio.sleep(10)
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Automatic Meta Ads synchronization failed")
            await asyncio.sleep(self.settings.meta_auto_sync_interval_minutes * 60)

    async def run_once(self) -> bool:
        token = self.settings.meta_access_token.get_secret_value()
        if not token or not self.settings.meta_ad_account_ids:
            return False

        async with AsyncSessionFactory() as session:
            tenant = await session.scalar(
                select(Tenant).where(
                    Tenant.slug == self.settings.meta_tenant_slug,
                    Tenant.is_active.is_(True),
                )
            )
            if tenant is None:
                logger.error("Meta tenant slug %s was not found", self.settings.meta_tenant_slug)
                return False

            lock_key = f"revora-meta-sync:{tenant.id}"
            locked = await session.scalar(
                text("SELECT pg_try_advisory_lock(hashtext(:lock_key))"),
                {"lock_key": lock_key},
            )
            if not locked:
                logger.info("Automatic Meta Ads synchronization is already running")
                return False

            try:
                # Session scope is deliberate: the service may commit an error state.
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, false)"),
                    {"tenant_id": str(tenant.id)},
                )
                now = datetime.now(ZoneInfo(tenant.timezone))
                date_to = now.date()
                date_from = date_to - timedelta(
                    days=self.settings.meta_auto_sync_lookback_days - 1
                )
                client = MetaAdsClient(
                    token,
                    self.settings.meta_graph_api_version,
                    attribution_windows=self.settings.meta_attribution_windows,
                    action_report_time=self.settings.meta_action_report_time,
                )
                service = MarketingService(
                    MarketingRepository(session),
                    meta_client=client,
                    meta_account_ids=self.settings.meta_ad_account_ids,
                    meta_attribution_windows=self.settings.meta_attribution_windows,
                    meta_action_report_time=self.settings.meta_action_report_time,
                    meta_auto_sync_enabled=True,
                )
                result = await service.sync_meta_for_tenant(
                    tenant.id, date_from, date_to
                )
                await session.commit()
                logger.info(
                    "Automatic Meta Ads synchronization completed accounts=%s rows=%s",
                    result.accounts_synced,
                    result.rows_written,
                )
                return True
            finally:
                await session.rollback()
                await session.execute(text("SELECT set_config('app.tenant_id', '', false)"))
                await session.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:lock_key))"),
                    {"lock_key": lock_key},
                )
                await session.commit()
