"""ORM models: Job, Usage, and the optional account system (User, Work)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.models import JobStatus
from app.database import Base, utcnow

#: statuses that occupy a queue slot
ACTIVE_STATUSES: tuple[str, ...] = (JobStatus.QUEUED.value, JobStatus.PROCESSING.value)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    session_token: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.QUEUED.value)
    stage: Mapped[str | None] = mapped_column(String(16), nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    model_size: Mapped[str] = mapped_column(String(32))
    tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    denoise_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    loudnorm_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    llm_correction_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    segments_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Usage(Base):
    __tablename__ = "usage"
    __table_args__ = (UniqueConstraint("session_token", "date", name="uq_usage_token_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_token: Mapped[str] = mapped_column(String(64), index=True)
    date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD (UTC)
    uploaded_seconds: Mapped[float] = mapped_column(Float, default=0.0)

    @classmethod
    def upsert(cls, db: Session, session_token: str, date: str, add_seconds: float) -> Usage:
        """Add ``add_seconds`` to today's usage row for the token (create if absent)."""
        row = db.scalar(
            select(cls).where(cls.session_token == session_token, cls.date == date)
        )
        if row is None:
            row = cls(session_token=session_token, date=date, uploaded_seconds=add_seconds)
            db.add(row)
        else:
            row.uploaded_seconds += add_seconds
        return row


class User(Base):
    """Optional account: email + PBKDF2 password hash + display name.

    Accounts are a pure overlay on the anonymous session flow — a job is still
    owned by its ``session_token``; the account only adds a persistent identity
    that can claim jobs into a personal library (see ``Work``).
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: stored lowercased so the unique index enforces case-insensitive uniqueness
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Work(Base):
    """A saved job in a user's personal library (the "works" collection).

    ``job_id`` is deliberately NOT a foreign key: jobs are ephemeral (deleted
    by the TTL cleanup once ``expires_at`` passes) while works are meant to
    persist, so a hard FK would either block cleanup (RESTRICT) or cascade the
    work away (CASCADE). The works list reports ``job.status`` as ``expired``
    when the underlying job row is gone.
    """

    __tablename__ = "works"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_work_user_job"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
