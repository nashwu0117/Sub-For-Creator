"""Celery application for the Sub-for-Creator worker."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

celery_app = Celery("sfc", broker=get_settings().celery_broker_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # one task at a time per worker process; max_concurrent is enforced by
    # worker concurrency settings (the API only caps queue length)
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    beat_schedule={
        "cleanup-expired-jobs": {
            "task": "app.worker.cleanup.cleanup_expired_jobs",
            "schedule": crontab(minute="0", hour="*/6"),
        },
    },
)
