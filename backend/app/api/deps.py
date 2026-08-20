"""Shared API dependencies and job-lookup helpers."""

from __future__ import annotations

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from app.core.exceptions import JobNotFoundError, JobNotReadyError
from app.core.models import JobStatus
from app.database import utcnow
from app.models.db import Job


def session_token(
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
) -> str:
    """Require the anonymous-session header; opaque token, no format check.

    The client generates a UUID and sends it on every request; a missing or
    over-long header is a client error (400).
    """
    if not x_session_token or not x_session_token.strip():
        raise HTTPException(status_code=400, detail="X-Session-Token header required")
    token = x_session_token.strip()
    if len(token) > 64:
        raise HTTPException(
            status_code=400, detail="X-Session-Token header must be at most 64 characters"
        )
    return token


def require_job_access(job: Job, token: str) -> None:
    """Raise 403 unless the requester's session token owns ``job``."""
    if job.session_token != token:
        raise HTTPException(status_code=403, detail="job belongs to another session")


def get_job_or_404(db: Session, job_id: str) -> Job:
    """Load a job or raise the typed 404 error."""
    job = db.get(Job, job_id)
    if job is None:
        raise JobNotFoundError(f"job {job_id} not found")
    return job


def ensure_not_expired(db: Session, job: Job) -> Job:
    """Mark the job expired and raise 410 when its TTL has passed."""
    now = utcnow()
    if job.expires_at is not None and job.expires_at < now:
        job.status = JobStatus.EXPIRED.value
        db.commit()
        raise HTTPException(status_code=410, detail="Job expired")
    return job


def require_done(job: Job) -> None:
    """Raise 409 unless the job has finished processing."""
    if job.status != JobStatus.DONE.value:
        raise JobNotReadyError(f"job {job.id} is not ready (status={job.status})")
