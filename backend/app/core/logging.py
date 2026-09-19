"""Предсказуемое логирование для API и фоновых процессов."""

import logging
from logging.config import dictConfig


def configure_logging(level: str) -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "level": level,
                }
            },
            "root": {"handlers": ["console"], "level": level},
            # httpx logs its full request URL at INFO. Some providers put a
            # credential in that URL (Telegram Bot API), while telecom URLs
            # can contain a caller number. Never send either to Render logs.
            "loggers": {
                "httpx": {"handlers": ["console"], "level": "WARNING", "propagate": False},
                "httpcore": {"handlers": ["console"], "level": "WARNING", "propagate": False},
            },
        }
    )
    logging.captureWarnings(True)
