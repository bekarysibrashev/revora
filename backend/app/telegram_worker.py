"""Render/local process entry point for the Telegram staff bot."""

import asyncio

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.modules.telegram.bot import TelegramBotRunner


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    asyncio.run(TelegramBotRunner(settings).run_forever())


if __name__ == "__main__":
    main()

