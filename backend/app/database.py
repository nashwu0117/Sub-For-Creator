"""SQLAlchemy engine / session / base — single source for DB plumbing.

Timestamps are stored as naive UTC everywhere (see ``utcnow``); SQLite has no
timezone support and naive-UTC keeps SQL-level comparisons consistent.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

log = logging.getLogger(__name__)


def utcnow() -> datetime:
    """Naive UTC now (matches how all datetime columns are stored)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ensure_sqlite_dir(url: str) -> None:
    """Create the parent directory of a sqlite file so the engine can connect."""
    if url.startswith("sqlite"):
        path = url.removeprefix("sqlite:///")
        if path and path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)


def _build_engine():
    settings = get_settings()
    _ensure_sqlite_dir(settings.database_url)
    connect_args: dict = {}
    if settings.database_url.startswith("sqlite"):
        # check_same_thread=False: worker threads and request threads share the file
        connect_args = {"check_same_thread": False, "timeout": 30}
    return create_engine(settings.database_url, connect_args=connect_args)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (idempotent) and backfill columns on pre-existing DBs."""
    from app.models.db import Job, Usage, User, Work  # noqa: F401  (register models on Base)

    Base.metadata.create_all(bind=engine)
    _ensure_job_columns(engine)


#: columns added after the initial schema; ALTERed in on pre-existing SQLite DBs
_JOB_BACKFILL_COLUMNS: tuple[tuple[str, str], ...] = (
    ("tier", "VARCHAR(16)"),
    ("denoise_enabled", "BOOLEAN"),
    ("loudnorm_enabled", "BOOLEAN"),
    ("llm_correction_enabled", "BOOLEAN"),
)


def _ensure_job_columns(bind) -> None:
    """Idempotently add missing ``jobs`` columns (SQLite only, best-effort).

    ``create_all`` only creates missing tables — it never alters existing ones,
    so a dev DB created before the ASR-enhancement columns would crash on
    INSERT. PRAGMA + ALTER TABLE keeps those DBs working without a manual
    migration. Failures are logged and swallowed so startup never crashes.
    """
    if bind.dialect.name != "sqlite":
        return
    try:
        with bind.connect() as conn:
            existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(jobs)")}
            for name, ddl in _JOB_BACKFILL_COLUMNS:
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE jobs ADD COLUMN {name} {ddl}")
    except Exception:  # noqa: BLE001 - migration is best-effort
        log.warning("could not backfill jobs columns; run a manual migration", exc_info=True)
