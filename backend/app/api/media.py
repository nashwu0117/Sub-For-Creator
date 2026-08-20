"""GET /api/jobs/{job_id}/media and /audio — source file streaming for the player."""

from __future__ import annotations

import mimetypes
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import (
    current_user,
    ensure_not_expired,
    get_job_or_404,
    require_job_access,
    session_token,
)
from app.database import get_db
from app.models.db import User
from app.storage import audio_key, get_storage, source_key

router = APIRouter()


@router.get("/jobs/{job_id}/media")
def get_media(
    job_id: str,
    token: str = Depends(session_token),
    user: User | None = Depends(current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    job = get_job_or_404(db, job_id)
    ensure_not_expired(db, job)
    require_job_access(db, job, user, token)
    storage = get_storage()
    ext = os.path.splitext(job.filename)[1].lower() or ".bin"
    key = source_key(job.id, ext)
    if not storage.exists(key):
        raise HTTPException(status_code=404, detail="media file not found")
    media_type = mimetypes.guess_type(job.filename)[0] or "application/octet-stream"
    return FileResponse(
        storage.open_path(key),
        media_type=media_type,
        filename=os.path.basename(job.filename),
        content_disposition_type="inline",
    )


@router.get("/jobs/{job_id}/audio")
def get_audio(
    job_id: str,
    token: str = Depends(session_token),
    user: User | None = Depends(current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    job = get_job_or_404(db, job_id)
    ensure_not_expired(db, job)
    require_job_access(db, job, user, token)
    storage = get_storage()
    key = audio_key(job.id)
    if not storage.exists(key):
        raise HTTPException(status_code=404, detail="audio not available yet")
    return FileResponse(
        storage.open_path(key),
        media_type="audio/wav",
        filename="audio.wav",
        content_disposition_type="inline",
    )
