"""GET /api/metrics — Prometheus text-format metrics for production monitoring.

Exposes queue depth, job counts by status, worker concurrency, storage usage,
the active ASR backend, per-device GPU utilization/memory (via ``nvidia-smi``)
and a job-duration histogram. Every probe is wrapped so a temporarily
unavailable Redis/storage/GPU never fails the scrape — the endpoint always
returns valid Prometheus text with whatever is available.

The endpoint is intentionally unauthenticated so Prometheus can scrape it;
see ``docs/MONITORING.md`` for how to firewall it when the API is public.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime

from fastapi import APIRouter, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionLocal
from app.models.db import Job
from app.storage import LocalStorage, get_storage

log = logging.getLogger(__name__)

router = APIRouter()

#: TTLs for expensive probes (seconds) — survive scrape storms without hammering
#: the GPU driver, the object store or the filesystem.
_GPU_CACHE_TTL = 5.0
_STORAGE_CACHE_TTL = 10.0

#: Job-duration histogram buckets (seconds) — sub-second mock runs through
#: multi-hour large-v3 transcriptions.
_DURATION_BUCKETS = (
    1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600, 7200, 14400, 28800, 57600, float("inf"),
)

_registry = CollectorRegistry()

_jobs_total = Gauge(
    "sfc_jobs_total",
    "Number of jobs by status (queued/processing/done/failed/expired).",
    ["status"],
    registry=_registry,
)
_queue_depth = Gauge(
    "sfc_queue_depth",
    "Jobs queued or processing (same definition as the API queue-capacity check).",
    registry=_registry,
)
_workers_concurrency = Gauge(
    "sfc_workers_concurrency",
    "Jobs currently being processed (status=processing).",
    registry=_registry,
)
_storage_bytes = Gauge(
    "sfc_storage_bytes",
    "Total bytes stored in the storage backend (local disk or S3).",
    registry=_registry,
)
_storage_objects = Gauge(
    "sfc_storage_objects",
    "Total number of stored objects/files.",
    registry=_registry,
)
_gpu_utilization = Gauge(
    "sfc_gpu_utilization_percent",
    "GPU utilization percentage per device (nvidia-smi).",
    ["gpu"],
    registry=_registry,
)
_gpu_memory_used = Gauge(
    "sfc_gpu_memory_used_bytes",
    "GPU memory used in bytes per device (nvidia-smi).",
    ["gpu"],
    registry=_registry,
)
_gpu_memory_total = Gauge(
    "sfc_gpu_memory_total_bytes",
    "GPU memory total in bytes per device (nvidia-smi).",
    ["gpu"],
    registry=_registry,
)
_gpu_present = Gauge(
    "sfc_gpu_present",
    "1 when nvidia-smi reported at least one GPU, 0 otherwise.",
    registry=_registry,
)
_asr_backend = Gauge(
    "sfc_asr_backend",
    "Active ASR backend (info-style gauge: 1 on the active backend, 0 elsewhere).",
    ["backend"],
    registry=_registry,
)
_job_duration = Histogram(
    "sfc_job_duration_seconds",
    "Wall-clock duration of completed jobs (completed_at - created_at).",
    buckets=_DURATION_BUCKETS,
    registry=_registry,
)

#: last known GPU count, so unavailable GPUs can be zeroed instead of dropped
_last_gpu_count = 0

#: cursor for the duration histogram — only newly-completed jobs are observed
_last_completed_at: datetime | None = None
_duration_lock = threading.Lock()


class _TTLCache:
    """Thread-safe value cache with a monotonic-clock TTL."""

    def __init__(self, ttl: float):
        self._ttl = ttl
        self._lock = threading.Lock()
        self._value: object | None = None
        self._expires = 0.0

    def get(self, producer: object) -> object:
        now = time.monotonic()
        with self._lock:
            if self._value is not None and now < self._expires:
                return self._value
            value = producer()
            self._value = value
            self._expires = now + self._ttl
            return value


_gpu_cache = _TTLCache(_GPU_CACHE_TTL)
_storage_cache = _TTLCache(_STORAGE_CACHE_TTL)


def _probe_gpu() -> list[tuple[int, int, int]] | None:
    """Return [(util_pct, mem_used_mib, mem_total_mib), ...] or None if unavailable."""
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        return None
    try:
        proc = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    stats: list[tuple[int, int, int]] = []
    for line in proc.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3:
            continue
        try:
            stats.append((int(parts[0]), int(parts[1]), int(parts[2])))
        except ValueError:
            continue
    return stats or None


def _probe_storage() -> tuple[int, int]:
    """Return (total_bytes, object_count) for the configured storage backend."""
    storage = get_storage()
    if isinstance(storage, LocalStorage):
        total = 0
        count = 0
        for dirpath, _dirnames, filenames in os.walk(storage.base_dir):
            for filename in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, filename))
                except OSError:
                    continue
                count += 1
        return total, count
    # S3-compatible backend: paginated list_objects_v2 (cached, so cheap per scrape).
    client = storage._client()  # noqa: SLF001 — same codebase, avoids re-wiring boto3
    paginator = client.get_paginator("list_objects_v2")
    total = 0
    count = 0
    for page in paginator.paginate(Bucket=storage.bucket):
        for obj in page.get("Contents", []):
            total += int(obj["Size"])
            count += 1
    return total, count


def _collect_job_stats() -> dict[str, int] | None:
    """One GROUP BY query (status -> count); None when the DB is unavailable."""
    try:
        db = SessionLocal()
        try:
            rows = db.execute(select(Job.status, func.count()).group_by(Job.status)).all()
            return {status: count for status, count in rows}
        finally:
            db.close()
    except Exception:
        log.exception("metrics: job stats query failed")
        return None


def _observe_job_durations(db: object) -> None:
    """Observe durations of jobs completed since the last scrape (bounded query)."""
    global _last_completed_at
    rows = db.execute(
        select(Job.completed_at, Job.created_at)
        .where(Job.status == "done", Job.completed_at.is_not(None))
        .order_by(Job.completed_at.desc())
        .limit(1000)
    ).all()
    if not rows:
        return
    with _duration_lock:
        cursor = _last_completed_at
        for completed_at, created_at in reversed(rows):
            if cursor is not None and completed_at <= cursor:
                continue
            duration = (completed_at - created_at).total_seconds()
            if duration >= 0:
                _job_duration.observe(duration)
        _last_completed_at = rows[0][0]


def _collect() -> str:
    """Refresh gauges and return the Prometheus text exposition."""
    global _last_gpu_count
    counts = _collect_job_stats()
    if counts is not None:
        for status in ("queued", "processing", "done", "failed", "expired"):
            _jobs_total.labels(status=status).set(counts.get(status, 0))
        _queue_depth.set(counts.get("queued", 0) + counts.get("processing", 0))
        _workers_concurrency.set(counts.get("processing", 0))

    try:
        db = SessionLocal()
        try:
            _observe_job_durations(db)
        finally:
            db.close()
    except Exception:
        log.exception("metrics: job duration observation failed")

    try:
        total_bytes, objects = _storage_cache.get(_probe_storage)
        _storage_bytes.set(total_bytes)
        _storage_objects.set(objects)
    except Exception:
        log.exception("metrics: storage probe failed")

    gpu_comment = ""
    try:
        gpus = _gpu_cache.get(_probe_gpu)
    except Exception:
        log.exception("metrics: GPU probe failed")
        gpus = None
    if gpus is None:
        gpu_comment = (
            "# sfc_gpu_* metrics unavailable: nvidia-smi not found or failed "
            "(no NVIDIA driver in this container)\n"
        )
        _gpu_present.set(0)
        for i in range(_last_gpu_count):
            _gpu_utilization.labels(gpu=str(i)).set(0)
            _gpu_memory_used.labels(gpu=str(i)).set(0)
            _gpu_memory_total.labels(gpu=str(i)).set(0)
    else:
        _gpu_present.set(1)
        for i in range(max(len(gpus), _last_gpu_count)):
            if i < len(gpus):
                util, used_mib, total_mib = gpus[i]
                _gpu_utilization.labels(gpu=str(i)).set(util)
                _gpu_memory_used.labels(gpu=str(i)).set(used_mib * 1024 * 1024)
                _gpu_memory_total.labels(gpu=str(i)).set(total_mib * 1024 * 1024)
            else:
                _gpu_utilization.labels(gpu=str(i)).set(0)
                _gpu_memory_used.labels(gpu=str(i)).set(0)
                _gpu_memory_total.labels(gpu=str(i)).set(0)
        _last_gpu_count = len(gpus)

    active_backend = os.environ.get("SFC_ASR_BACKEND", "whisperx")
    for backend in ("whisperx", "faster-whisper", "mock"):
        _asr_backend.labels(backend=backend).set(1 if backend == active_backend else 0)

    return gpu_comment + generate_latest(_registry).decode()


@router.get("/metrics")
def metrics() -> Response:
    """Prometheus text-format exposition (no auth — see docs/MONITORING.md)."""
    if not get_settings().metrics_enabled:
        return Response(status_code=404, content="metrics disabled (SFC_METRICS_ENABLED=false)")
    return Response(content=_collect(), media_type=CONTENT_TYPE_LATEST)
