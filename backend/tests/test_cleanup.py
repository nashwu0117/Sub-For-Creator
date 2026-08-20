"""TTL cleanup tests: expired jobs (rows + storage dirs)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.database import SessionLocal, utcnow
from app.models.db import Job
from app.storage import audio_key, get_storage, source_key
from app.worker.cleanup import cleanup_expired_jobs

pytestmark = pytest.mark.usefixtures("mock_asr")


def _seed_job(expires_at, token: str = "cleanup-tok", with_files: bool = False) -> str:
    db = SessionLocal()
    job = Job(
        id=uuid.uuid4().hex,
        session_token=token,
        status="done",
        filename="x.mp4",
        language="zh",
        model_size="large-v3",
        duration=2.0,
        expires_at=expires_at,
    )
    db.add(job)
    db.commit()
    db.close()
    if with_files:
        storage = get_storage()
        storage.save(b"fake-video", source_key(job.id, ".mp4"))
        storage.save(b"fake-audio", audio_key(job.id))
    return job.id


def _job_exists(job_id: str) -> bool:
    db = SessionLocal()
    try:
        return db.get(Job, job_id) is not None
    finally:
        db.close()


def test_cleanup_removes_expired_job_and_files():
    job_id = _seed_job(expires_at=utcnow() - timedelta(hours=1), with_files=True)
    storage = get_storage()
    assert storage.exists(source_key(job_id, ".mp4"))

    deleted = cleanup_expired_jobs()

    assert deleted >= 1
    assert not _job_exists(job_id)
    assert not storage.exists(source_key(job_id, ".mp4"))
    assert not storage.exists(audio_key(job_id))


def test_cleanup_keeps_future_jobs():
    job_id = _seed_job(expires_at=utcnow() + timedelta(hours=48))
    deleted = cleanup_expired_jobs()
    assert deleted == 0
    assert _job_exists(job_id)


def test_cleanup_returns_count():
    first = _seed_job(expires_at=utcnow() - timedelta(minutes=5))
    second = _seed_job(expires_at=utcnow() - timedelta(minutes=1))
    deleted = cleanup_expired_jobs()
    assert deleted >= 2
    assert not _job_exists(first)
    assert not _job_exists(second)





def test_celery_registry_includes_task_modules():
    """Worker must know process_job / cleanup tasks (regression: KeyError
    'app.worker.tasks.process_job' when redis queue is enabled)."""
    import app.worker.cleanup  # noqa: F401
    import app.worker.tasks  # noqa: F401
    from app.worker.celery_app import celery_app

    assert "app.worker.tasks.process_job" in celery_app.tasks
    assert "app.worker.cleanup.cleanup_expired_jobs" in celery_app.tasks
