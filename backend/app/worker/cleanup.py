"""TTL cleanup: delete expired jobs (storage dir + DB row) and stale usage rows."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.database import SessionLocal, utcnow
from app.models.db import Job, Usage
from app.storage import get_storage
from app.worker.celery_app import celery_app

log = logging.getLogger(__name__)

#: usage rows older than this many days are pruned during cleanup
USAGE_RETENTION_DAYS = 7


def cleanup_expired_jobs() -> int:
    """Delete every job whose ``expires_at`` has passed, plus stale usage rows.

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

        cutoff = (
            datetime.now(timezone.utc).date() - timedelta(days=USAGE_RETENTION_DAYS)
        ).isoformat()
        db.execute(delete(Usage).where(Usage.date < cutoff))
        db.commit()
    finally:
        db.close()
    if deleted:
        log.info("cleanup removed %d expired job(s)", deleted)
    return deleted


cleanup_task = celery_app.task(cleanup_expired_jobs)
