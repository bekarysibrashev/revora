"""Общая точка входа Celery worker, beat и Flower."""

from celery import Celery

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

celery_app = Celery(
    "revora",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.modules.ai.insights.jobs"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=settings.timezone,
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "generate-v1-insights-daily": {
            "task": "revora.generate_insights",
            "schedule": 60 * 60 * 24,
        }
    },
)
