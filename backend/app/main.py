"""FastAPI app factory: DB init, CORS, routers, exception mapping, startup sweep."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import config as config_router
from app.api import export as export_router
from app.api import fonts as fonts_router
from app.api import health as health_router
from app.api import jobs as jobs_router
from app.api import media as media_router
from app.api import subtitles as subtitles_router
from app.api import uploads as uploads_router
from app.config import get_settings
from app.core.exceptions import (
    ASRError,
    AudioExtractionError,
    ExportError,
    JobNotFoundError,
    JobNotReadyError,
    MediaProcessingError,
    QuotaExceededError,
    RenderError,
    UnsupportedFormatError,
)
from app.core.fonts import sync_fonts
from app.database import init_db
from app.storage import get_storage
from app.worker.cleanup import cleanup_expired_jobs
from app.worker.queue import get_queue

log = logging.getLogger(__name__)

#: inline-mode cleanup sweep interval
CLEANUP_INTERVAL_SECONDS = 6 * 3600


def _cleanup_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(CLEANUP_INTERVAL_SECONDS):
        try:
            cleanup_expired_jobs()
        except Exception:
            log.exception("cleanup sweep failed")


def _register_exception_handlers(app: FastAPI) -> None:
    def _json(status: int, message: str) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": message})

    app.add_exception_handler(
        JobNotFoundError, lambda req, exc: _json(404, str(exc) or "job not found")
    )
    app.add_exception_handler(
        JobNotReadyError, lambda req, exc: _json(409, str(exc) or "job not ready")
    )
    app.add_exception_handler(
        QuotaExceededError,
        lambda req, exc: JSONResponse(
            status_code=429,
            content={
                "detail": str(exc) or "quota exceeded",
                "retry_after_seconds": getattr(exc, "retry_after_seconds", 60),
            },
        ),
    )
    app.add_exception_handler(
        UnsupportedFormatError, lambda req, exc: _json(400, str(exc) or "unsupported format")
    )
    app.add_exception_handler(
        AudioExtractionError, lambda req, exc: _json(400, str(exc) or "audio extraction failed")
    )
    app.add_exception_handler(
        MediaProcessingError, lambda req, exc: _json(400, str(exc) or "media processing failed")
    )
    app.add_exception_handler(
        RenderError, lambda req, exc: _json(504, str(exc) or "render failed")
    )
    app.add_exception_handler(
        ExportError, lambda req, exc: _json(500, str(exc) or "export failed")
    )
    app.add_exception_handler(
        ASRError, lambda req, exc: _json(500, str(exc) or "ASR failed")
    )


def create_app() -> FastAPI:
    """Build the application: tables, CORS, routers, startup cleanup sweep."""
    settings = get_settings()
    init_db()

    stop_event = threading.Event()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            deleted = cleanup_expired_jobs()
            log.info("startup cleanup removed %d expired job(s)", deleted)
        except Exception:
            log.exception("startup cleanup failed")
        try:
            registered = sync_fonts(get_storage())
            log.info("startup font sync registered %d font(s)", registered)
        except Exception:
            log.exception("startup font sync failed")
        get_queue()  # init the queue (inline executor or celery probe) up front
        if get_settings().queue_backend == "inline":
            thread = threading.Thread(
                target=_cleanup_loop, args=(stop_event,), name="sfc-cleanup", daemon=True
            )
            thread.start()
        yield
        stop_event.set()

    app = FastAPI(title="Sub for Creator", version=settings.version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_origins != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in (
        health_router.router,
        config_router.router,
        jobs_router.router,
        uploads_router.router,
        subtitles_router.router,
        media_router.router,
        export_router.router,
        fonts_router.router,
    ):
        app.include_router(router, prefix="/api")

    _register_exception_handlers(app)
    return app


app = create_app()
