"""ORM models: Job (the only table — anonymous, session-token owned)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

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
