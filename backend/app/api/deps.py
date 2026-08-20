"""Shared API dependencies and job-lookup helpers."""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.exceptions import JobNotFoundError, JobNotReadyError
from app.core.models import JobStatus
from app.database import get_db, utcnow
from app.models.db import Job, User, Work


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


def _sign_session_cookie(user_id: int, settings: Settings) -> str:
    """Sign ``{user_id}.{expiry}.{hmac}`` with HMAC-SHA256 (stateless cookie)."""
    expiry = int(time.time()) + settings.auth_session_days * 86400
    payload = f"{user_id}.{expiry}"
    digest = hmac.new(
        settings.auth_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload}.{digest}"


def _verify_session_cookie(cookie: str, settings: Settings) -> int | None:
    """Return the user id from a signed cookie, or None when invalid/expired."""
    try:
        user_id_str, expiry_str, digest = cookie.split(".")
        user_id = int(user_id_str)
        expiry = int(expiry_str)
    except (ValueError, AttributeError):
        return None
    payload = f"{user_id}.{expiry}"
    expected = hmac.new(
        settings.auth_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, digest):
        return None
    if expiry < time.time():
        return None
    return user_id


def current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    """Resolve the authenticated user from the signed cookie, or None.

    Auth is strictly optional: anonymous requests (no cookie, bad cookie, or
    deleted user) simply yield None and every route keeps working as before.
    """
    settings = get_settings()
    cookie = request.cookies.get(settings.auth_cookie_name)
    if not cookie:
        return None
    user_id = _verify_session_cookie(cookie, settings)
    if user_id is None:
        return None
    return db.get(User, user_id)


def require_job_access(db: Session, job: Job, user: User | None, token: str) -> None:
    """Raise 403 unless the requester may access ``job``.

    Ownership rules:
    - A claimed job (a ``Work`` row exists) is accessible only by its owner.
    - An unclaimed job is accessible only by the session token that created it.
    """
    claimed = db.scalar(select(Work).where(Work.job_id == job.id))
    if claimed is not None:
        if user is None or claimed.user_id != user.id:
            raise HTTPException(status_code=403, detail="job belongs to another user")
        return
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
