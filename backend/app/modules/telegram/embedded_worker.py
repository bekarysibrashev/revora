"""Run the Telegram staff bot inside the existing web service."""

import asyncio
from contextlib import suppress
import logging

from app.core.config import Settings
from app.modules.telegram.bot import TelegramBotRunner

logger = logging.getLogger(__name__)


class EmbeddedTelegramWorker:
    """Lifecycle wrapper that avoids a separately billed Render worker."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._task: asyncio.Task[None] | None = None
        self.last_error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.settings.telegram_bot_token.get_secret_value())

    @property
    def running(self) -> bool:
        return (
            self._task is not None
            and not self._task.done()
            and self.last_error is None
        )

    def start(self) -> None:
        if not self.configured:
            logger.warning("Telegram bot token is missing; embedded bot is disabled")
            return
        if self._task is None or self._task.done():
            self.last_error = None
            self._task = asyncio.create_task(self._run(), name="revora-telegram-bot")
            logger.info("Embedded Telegram staff bot scheduled")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("Embedded Telegram staff bot stopped")

    async def _run(self) -> None:
        while True:
            try:
                self.last_error = None
                await TelegramBotRunner(self.settings).run_forever()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)[:500]
                logger.exception("Embedded Telegram staff bot failed; retrying")
                await asyncio.sleep(10)
