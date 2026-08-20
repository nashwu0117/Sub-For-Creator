"""GET/PUT /api/jobs/{job_id}/subtitles — read and edit subtitle data."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import (
    current_user,
    ensure_not_expired,
    get_job_or_404,
    require_done,
    require_job_access,
    session_token,
)
from app.config import Settings, get_settings
from app.core.models import Segment, Word
from app.database import get_db
from app.models.db import User
from app.schemas import SubtitlesUpdate
from app.worker.serialization import json_to_segments, segments_to_json

router = APIRouter()


@router.get("/jobs/{job_id}/subtitles")
def get_subtitles(
    job_id: str,
    token: str = Depends(session_token),
    user: User | None = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    job = get_job_or_404(db, job_id)
    ensure_not_expired(db, job)
    require_done(job)
    require_job_access(db, job, user, token)
    return {
        "job_id": job.id,
        "language": job.language,
        "segments": json_to_segments(job.segments_json) if job.segments_json else [],
        "meta": {
            "model_size": job.model_size,
            "max_line_chars": settings.max_line_chars,
        },
    }


@router.put("/jobs/{job_id}/subtitles")
def put_subtitles(
    job_id: str,
    payload: SubtitlesUpdate,
    token: str = Depends(session_token),
    user: User | None = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    job = get_job_or_404(db, job_id)
    ensure_not_expired(db, job)
    require_done(job)
    require_job_access(db, job, user, token)

    existing = (
        {seg.id: seg for seg in json_to_segments(job.segments_json)}
        if job.segments_json
        else {}
    )
    merged: list[Segment] = []
    for seg in payload.segments:
        words: list[Word] = []
        if seg.words:
            words = [
                Word(text=w.text or w.word or "", start=w.start, end=w.end) for w in seg.words
            ]
        elif seg.id in existing:
            words = existing[seg.id].words
        merged.append(Segment(id=seg.id, start=seg.start, end=seg.end, text=seg.text, words=words))

    job.segments_json = segments_to_json(merged)
    db.commit()
    return {"ok": True}
