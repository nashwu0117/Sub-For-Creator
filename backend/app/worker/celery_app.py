"""Celery application for the Sub-for-Creator worker.

Queue topology (multi-GPU horizontal scaling):

    transcribe  — GPU ASR (``process_job_task``), the heavy task
    render      — ffmpeg burn-in (``render_job``), CPU/GPU-optional
    celery      — default queue for light work (cleanup beat tasks)

``task_routes`` pins each task to its queue; workers opt into queues with
``-Q``. The default single worker consumes all three so a one-worker
deployment behaves exactly as before. ``worker_prefetch_multiplier=1`` +
``task_acks_late=True`` apply to every queue: a crashed worker's in-flight
task is redelivered after the visibility timeout instead of being lost.
"""

from __future__ import annotations

import logging
import os

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

log = logging.getLogger(__name__)


def _apply_gpu_affinity() -> None:
    """Pin this process to one GPU via ``CUDA_VISIBLE_DEVICES`` (SFC_GPU_INDEX).

    Must run before torch/CUDA initializes; the ASR backends import torch
    lazily inside ``transcribe()``, so setting the env var at import time is
    sufficient. ``None`` (unset) leaves ``CUDA_VISIBLE_DEVICES`` untouched so
    a single-GPU host sees every device as before.
    """
    index = get_settings().gpu_index
    if index is None:
        return
    if index < 0:
        log.warning("SFC_GPU_INDEX must be >= 0; ignoring %s", index)
        return
    os.environ["CUDA_VISIBLE_DEVICES"] = str(index)
    log.info("pinned CUDA_VISIBLE_DEVICES=%s (SFC_GPU_INDEX=%s)", index, index)


_apply_gpu_affinity()

_settings = get_settings()

celery_app = Celery(
    "sfc",
    broker=_settings.celery_broker_url,
    include=["app.worker.tasks", "app.worker.cleanup", "app.worker.render_tasks"],
)
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
    task_default_queue=_settings.default_queue,
    task_routes={
        "app.worker.tasks.process_job_task": {"queue": _settings.transcribe_queue},
        "app.worker.render_tasks.render_job": {"queue": _settings.render_queue},
        "app.worker.cleanup.cleanup_expired_jobs": {"queue": _settings.default_queue},
    },
    beat_schedule={
        "cleanup-expired-jobs": {
            "task": "app.worker.cleanup.cleanup_expired_jobs",
            "schedule": crontab(minute="0", hour="*/6"),
        },
    },
)
