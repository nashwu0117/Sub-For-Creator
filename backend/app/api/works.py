"""Works collection: a user's saved transcription jobs.

A "work" claims an anonymous job (owned by the requester's ``X-Session-Token``)
into the user's personal library. Jobs stay ephemeral (48h TTL); the work row
outlives the job and reports ``job.status`` as ``expired`` once the job is gone.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_job_or_404, session_token
from app.database import get_db
from app.models.db import Job, User, Work

router = APIRouter()


def _work_payload(work: Work, job: Job | None) -> dict:
    return {
        "id": work.id,
        "job_id": work.job_id,
        "title": work.title,
        "created_at": work.created_at.isoformat() if work.created_at else None,
        "job": {
            "status": job.status if job is not None else "expired",
            "filename": job.filename if job is not None else None,
            "duration": job.duration if job is not None else None,
            "expires_at": (
                job.expires_at.isoformat() if job is not None and job.expires_at else None
            ),
        },
    }


def _require_user(user: User | None) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


@router.get("/works")
def list_works(
    user: User | None = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """List the current user's works, newest first, with live job status."""
    user = _require_user(user)
    works = db.scalars(
        select(Work).where(Work.user_id == user.id).order_by(Work.created_at.desc())
    ).all()
    jobs = {
        job.id: job
        for job in db.scalars(
            select(Job).where(Job.id.in_([work.job_id for work in works]))
        ).all()
    }
    return [_work_payload(work, jobs.get(work.job_id)) for work in works]


@router.post("/works/{job_id}")
def claim_work(
    job_id: str,
    token: str = Depends(session_token),
    user: User | None = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Claim an anonymous job the session token owns into the user's library.

    Idempotent: claiming an already-claimed job returns the existing work.
    """
    user = _require_user(user)
    job = get_job_or_404(db, job_id)
    existing = db.scalar(select(Work).where(Work.job_id == job.id))
    if existing is not None:
        if existing.user_id != user.id:
            raise HTTPException(status_code=403, detail="job belongs to another user")
        return _work_payload(existing, job)
    if job.session_token != token:
        raise HTTPException(status_code=403, detail="job belongs to another session")
    title = os.path.splitext(job.filename)[0] or job.filename
    work = Work(user_id=user.id, job_id=job.id, title=title)
    db.add(work)
    db.commit()
    db.refresh(work)
    return _work_payload(work, job)


@router.get("/works/{work_id}")
def get_work(
    work_id: int,
    user: User | None = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return one work with its live job status."""
    user = _require_user(user)
    work = db.get(Work, work_id)
    if work is None:
        raise HTTPException(status_code=404, detail="work not found")
    if work.user_id != user.id:
        raise HTTPException(status_code=403, detail="work belongs to another user")
    return _work_payload(work, db.get(Job, work.job_id))


@router.delete("/works/{work_id}")
def delete_work(
    work_id: int,
    user: User | None = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Remove a work from the user's library (the job itself is untouched)."""
    user = _require_user(user)
    work = db.get(Work, work_id)
    if work is None:
        raise HTTPException(status_code=404, detail="work not found")
    if work.user_id != user.id:
        raise HTTPException(status_code=403, detail="work belongs to another user")
    db.delete(work)
    db.commit()
    return {"ok": True}
