"""GET /api/config — upload limits and supported languages for the frontend."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import session_token
from app.api.limits import get_usage_seconds
from app.config import SUPPORTED_LANGUAGES, Settings, get_settings
from app.database import get_db

router = APIRouter()


@router.get("/config")
def config(
    token: str = Depends(session_token),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    remaining = max(0, settings.daily_seconds_per_session - get_usage_seconds(db, token))
    return {
        "max_upload_mb": settings.max_upload_mb,
        "max_duration_min": settings.max_duration_min,
        "max_queue": settings.max_queue,
        "supported_languages": SUPPORTED_LANGUAGES,
        "session_remaining_seconds": remaining,
        "default_options": {
            "max_line_chars": settings.max_line_chars,
            "model_size": settings.whisper_model,
        },
    }
