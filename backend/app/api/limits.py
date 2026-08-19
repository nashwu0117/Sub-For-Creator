"""Rate limiting and quota enforcement (upload frequency, daily seconds, queue)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.exceptions import QuotaExceededError
from app.models.db import ACTIVE_STATUSES, Job, Usage

#: sliding window for the upload-frequency limit (seconds)
RATE_WINDOW_SECONDS = 60.0

_uploads: dict[str, deque[float]] = defaultdict(deque)
_uploads_lock = threading.Lock()


def _quota_error(message: str, retry_after_seconds: int) -> QuotaExceededError:
    exc = QuotaExceededError(message)
    exc.retry_after_seconds = retry_after_seconds
    return exc


def check_upload_rate(token: str) -> None:
    """Sliding-window upload frequency limit (``SFC_UPLOAD_RATE_LIMIT`` per 60s)."""
    settings = get_settings()
    if settings.upload_rate_limit <= 0:
        return
    now = time.monotonic()
    with _uploads_lock:
        window = _uploads[token]
        while window and now - window[0] > RATE_WINDOW_SECONDS:
            window.popleft()
        if len(window) >= settings.upload_rate_limit:
            retry = int(RATE_WINDOW_SECONDS - (now - window[0])) + 1
            raise _quota_error(
                f"upload rate limit exceeded; retry in {retry}s", retry
            )
        window.append(now)


def reset_rate_limits() -> None:
    """Clear all rate-limit state (test isolation)."""
    with _uploads_lock:
        _uploads.clear()


def today_str() -> str:
    """UTC date as YYYY-MM-DD (usage rows are keyed by UTC day)."""
    return datetime.now(timezone.utc).date().isoformat()


def get_usage_seconds(db: Session, token: str) -> float:
    """Seconds already uploaded today by this session token."""
    row = db.scalar(
        select(Usage).where(Usage.session_token == token, Usage.date == today_str())
    )
    return row.uploaded_seconds if row is not None else 0.0


def check_daily_quota(db: Session, token: str, duration: float) -> None:
    """Reject when today's usage plus ``duration`` exceeds the daily cap."""
    settings = get_settings()
    if settings.daily_seconds_per_session <= 0:
        return
    used = get_usage_seconds(db, token)
    if used + duration > settings.daily_seconds_per_session:
        raise _quota_error(
            "daily upload quota exceeded; try again tomorrow", 60
        )


def record_usage(db: Session, token: str, duration: float) -> None:
    """Add ``duration`` to today's usage row (caller commits)."""
    Usage.upsert(db, token, today_str(), duration)


def queue_length(db: Session) -> int:
    """Number of jobs currently queued or processing."""
    return (
        db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.status.in_(ACTIVE_STATUSES))
        )
        or 0
    )


def check_queue_capacity(db: Session) -> None:
    """Reject when the active queue already holds ``SFC_MAX_QUEUE`` jobs."""
    settings = get_settings()
    if settings.max_queue <= 0:
        return
    if queue_length(db) >= settings.max_queue:
        raise _quota_error("queue is full; try again later", 60)
