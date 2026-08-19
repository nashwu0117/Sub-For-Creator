"""Job queue abstraction: Celery broker or in-process inline executor.

``get_queue()`` returns a module-level cached singleton. When
``settings.queue_backend`` is ``celery`` but the broker is unreachable
(redis ping fails within ~1s), we log a warning and fall back to the inline
queue so the service keeps working without a broker.
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from app.config import get_settings

log = logging.getLogger(__name__)


class JobQueue(ABC):
    """Dispatches a job id to a worker."""

    @abstractmethod
    def enqueue(self, job_id: str) -> None:
        """Queue ``job_id`` for processing (non-blocking)."""


class CeleryJobQueue(JobQueue):
    """Dispatches via the Celery task ``process_job_task``."""

    def enqueue(self, job_id: str) -> None:
        from app.worker.tasks import process_job_task

        process_job_task.delay(job_id)


class InlineJobQueue(JobQueue):
    """Runs ``process_job`` in a bounded thread pool (no broker needed).

    Concurrency is capped at ``settings.max_concurrent``; the executor
    reference is kept on the instance so worker threads are never GC'd.
    """

    def __init__(self, max_workers: int):
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="sfc-inline"
        )

    def enqueue(self, job_id: str) -> None:
        from app.worker.tasks import process_job

        self._executor.submit(process_job, job_id)


_queue: JobQueue | None = None
_queue_lock = threading.Lock()


def _probe_broker(url: str) -> None:
    """Raise if the redis broker is unreachable (quick ping, <=1s)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("redis", "rediss"):
        return  # non-redis brokers are trusted; send errors surface at dispatch
    import redis

    client = redis.Redis(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
    )
    client.ping()


def get_queue() -> JobQueue:
    """Cached queue singleton honoring ``settings.queue_backend``."""
    global _queue
    with _queue_lock:
        if _queue is not None:
            return _queue
        settings = get_settings()
        if settings.queue_backend == "inline":
            _queue = InlineJobQueue(settings.max_concurrent)
        else:
            try:
                _probe_broker(settings.celery_broker_url)
                _queue = CeleryJobQueue()
            except Exception as exc:  # broker down or unreachable
                log.warning(
                    "celery broker %s unreachable (%s); falling back to inline queue",
                    settings.celery_broker_url,
                    exc,
                )
                _queue = InlineJobQueue(settings.max_concurrent)
        return _queue
