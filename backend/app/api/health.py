"""GET /api/health — liveness probe."""

from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings

router = APIRouter()


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {"status": "ok", "version": settings.version}
