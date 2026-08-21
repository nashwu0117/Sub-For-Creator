"""Rate limiting and queue-capacity enforcement (disabled for local use)."""

from __future__ import annotations

from sqlalchemy.orm import Session


def check_upload_rate(token: str) -> None:
    pass


def reset_rate_limits() -> None:
    pass


def queue_length(db: Session) -> int:
    return 0


def check_queue_capacity(db: Session) -> None:
    pass
