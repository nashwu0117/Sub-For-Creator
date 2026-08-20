"""TTL cleanup: delete expired jobs (storage dir + DB row) and abandoned chunked-upload sessions."""

from __future__ import annotations

import logging
import os
import shutil
import time

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal, utcnow
from app.models.db import Job
from app.storage import get_storage
from app.worker.celery_app import celery_app

log = logging.getLogger(__name__)

#: subdirectory under SFC_UPLOAD_DIR holding in-progress chunk sessions
CHUNKS_SUBDIR = ".chunks"


def _cleanup_stale_chunk_sessions() -> int:
    """Drop chunk-upload sessions older than SFC_TTL_HOURS (abandoned uploads)."""
    settings = get_settings()
    chunks_root = os.path.join(settings.upload_dir, CHUNKS_SUBDIR)
    if not os.path.isdir(chunks_root):
        return 0
    cutoff = time.time() - settings.ttl_hours * 3600
    removed = 0
    for entry in os.scandir(chunks_root):
        if not entry.is_dir():
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry.path, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    if removed:
        log.info("cleanup removed %d stale chunk session(s)", removed)
    return removed


def cleanup_expired_jobs() -> int:
    """Delete every job whose ``expires_at`` has passed.

    Returns the number of jobs deleted. Safe to call concurrently (each job
    dir/row is removed independently).
    """
    storage = get_storage()
    db = SessionLocal()
    deleted = 0
    try:
        now = utcnow()
        expired = db.scalars(
            select(Job).where(Job.expires_at.is_not(None), Job.expires_at < now)
        ).all()
        for job in expired:
            storage.delete_dir(f"jobs/{job.id}")
            db.delete(job)
            deleted += 1
        db.commit()
    finally:
        db.close()
    _cleanup_stale_chunk_sessions()
    if deleted:
        log.info("cleanup removed %d expired job(s)", deleted)
    return deleted


cleanup_task = celery_app.task(cleanup_expired_jobs)
