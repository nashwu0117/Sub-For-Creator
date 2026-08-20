"""Celery task for burned-in renders (mp4 / webm_alpha).

Renders used to run as in-process threads inside the API service, which
serialized encodes against the request workers. This module moves them onto
the ``render`` queue so a dedicated ``render-worker`` (or any worker with
``-Q render``) can run ffmpeg outside the API process.

The encode logic is reused verbatim from ``app.api.export``: ``_run_render``
(ffmpeg command + atomic rename) and ``_render_worker`` (DB lookup, cache
check, terminal state). The API process tracks ``rendering`` locally before
dispatching; ``ready`` is derived from the cached output file. Failures happen
in the worker process, so they are additionally persisted to a storage marker
(``jobs/<id>/<kind>.error``) that the API's ``render_status`` can surface.
"""

from __future__ import annotations

import logging

from app.api.export import RENDER_FORMATS, _get_render_state, _render_worker
from app.config import get_settings
from app.storage import get_storage, render_key
from app.worker.celery_app import celery_app

log = logging.getLogger(__name__)


def _render_error_key(job_id: str, fmt: str) -> str:
    """Storage key for the cross-process failure marker of a render."""
    return render_key(job_id, f"{RENDER_FORMATS[fmt][0]}.error")


def _persist_render_error(job_id: str, fmt: str, error: str) -> None:
    """Write the failure marker so the API process can surface it via /status."""
    try:
        get_storage().save(error.encode("utf-8"), _render_error_key(job_id, fmt))
    except Exception:  # noqa: BLE001 — a marker must never mask the render itself
        log.exception("failed to persist render error for %s/%s", job_id, fmt)


def render_job(job_id: str, fmt: str, params: dict) -> None:
    """Run the burn-in encode for ``job_id``/``fmt`` on the render queue.

    ``params`` holds the JSON-serializable render options (font_size,
    font_color, outline_color, font_family, karaoke, position). Settings are
    re-read inside the task so the worker process uses its own env.
    """
    _render_worker(job_id, fmt, get_settings(), params)
    state = _get_render_state(job_id, fmt)
    if state and state["status"] == "failed":
        _persist_render_error(job_id, fmt, state.get("error") or "render failed")


render_task = celery_app.task(render_job)
