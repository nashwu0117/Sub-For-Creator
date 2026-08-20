"""POST /api/jobs (upload) and GET /api/jobs/{job_id} (status)."""

from __future__ import annotations

import logging
import os
import tempfile
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import (
    current_user,
    ensure_not_expired,
    get_job_or_404,
    require_job_access,
    session_token,
)
from app.api.limits import (
    check_daily_quota,
    check_queue_capacity,
    check_upload_rate,
    record_usage,
)
from app.config import SUPPORTED_LANGUAGES, Settings, get_settings
from app.core.models import JobStatus
from app.database import get_db
from app.models.db import ACTIVE_STATUSES, Job, User
from app.schemas import JobOptions
from app.storage import get_storage, source_key
from app.worker.queue import get_queue

log = logging.getLogger(__name__)

router = APIRouter()


def _resolve_language(language: str | None) -> str | None:
    """Map ''/'auto'/None to auto-detect; reject unknown codes with 422."""
    if language in (None, "", "auto"):
        return None
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"unsupported language {language!r}")
    return language


def _parse_options(raw: str | None) -> JobOptions:
    if raw is None or not raw.strip():
        return JobOptions()
    try:
        return JobOptions.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "invalid options: expected JSON object with optional model_size"
                " and max_line_chars"
            ),
        ) from exc


def _queue_position(db: Session, job: Job) -> int:
    """1-based position among active jobs (created before or at this one)."""
    return (
        db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.status.in_(ACTIVE_STATUSES), Job.created_at <= job.created_at)
        )
        or 0
    )


def _finalize_upload(
    tmp_path: str,
    filename: str,
    token: str,
    language: str | None,
    options: str | None,
    db: Session,
    settings: Settings,
) -> JSONResponse:
    """Probe → quota → store → enqueue → respond. Shared by direct and chunked uploads."""
    # lazy import: core helpers live in app.core (probe raises 400 on bad media)
    from app.core import probe_duration, probe_media

    probe_media(tmp_path)  # UnsupportedFormatError/MediaProcessingError -> 400
    duration = probe_duration(tmp_path)
    if settings.max_duration_min > 0 and duration > settings.max_duration_min * 60:
        raise HTTPException(
            status_code=400,
            detail=(
                f"media duration {duration:.1f}s exceeds maximum of "
                f"{settings.max_duration_min} minutes"
            ),
        )

    lang = _resolve_language(language)
    opts = _parse_options(options)
    model_size = opts.model_size or settings.whisper_model

    check_daily_quota(db, token, duration)
    check_queue_capacity(db)

    ext = os.path.splitext(filename)[1].lower() or ".bin"
    job_id = uuid.uuid4().hex
    storage = get_storage()
    storage.save(tmp_path, source_key(job_id, ext))

    job = Job(
        id=job_id,
        session_token=token,
        status=JobStatus.QUEUED.value,
        filename=filename,
        language=lang,
        model_size=model_size,
        duration=duration,
    )
    db.add(job)
    db.flush()
    position = _queue_position(db, job)
    db.commit()

    try:
        get_queue().enqueue(job_id)
    except Exception as exc:
        log.exception("failed to enqueue job %s", job_id)
        job.status = JobStatus.FAILED.value
        job.error = f"enqueue failed: {exc}"[:500]
        db.commit()
    else:
        record_usage(db, token, duration)
        db.commit()

    # inline queue may already be processing/done — reflect the actual status
    db.expire_all()
    job = db.get(Job, job_id)
    active = job.status in ACTIVE_STATUSES
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job.id,
            "status": job.status,
            "queue_position": position if active else None,
            "eta_seconds": position * 60 if active else 0,
        },
    )


@router.post("/jobs")
def create_job(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    options: str | None = Form(None),
    token: str = Depends(session_token),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    check_upload_rate(token)

    filename = os.path.basename(file.filename or "upload")
    ext = os.path.splitext(filename)[1].lower() or ".bin"
    max_bytes = int(settings.max_upload_mb * 1024 * 1024)

    with tempfile.NamedTemporaryFile(prefix="sfc-upload-", suffix=ext, delete=False) as tmp:
        try:
            size = 0
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if max_bytes > 0 and size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"file exceeds maximum upload size of "
                            f"{settings.max_upload_mb} MB"
                        ),
                    )
                tmp.write(chunk)
            if size == 0:
                raise HTTPException(status_code=422, detail="empty file")

            return _finalize_upload(
                tmp.name, filename, token, language, options, db, settings
            )
        finally:
            os.unlink(tmp.name)


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    token: str = Depends(session_token),
    user: User | None = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(db, job_id)
    ensure_not_expired(db, job)
    require_job_access(db, job, user, token)
    position = _queue_position(db, job) if job.status in ACTIVE_STATUSES else None
    return {
        "job_id": job.id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "queue_position": position,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "expires_at": job.expires_at.isoformat() if job.expires_at else None,
        "meta": {
            "filename": job.filename,
            "duration": job.duration,
            "language": job.language,
            "model_size": job.model_size,
        },
    }
