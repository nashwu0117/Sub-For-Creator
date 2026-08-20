"""Job processing pipeline: extract audio -> transcribe -> segment -> persist.

``process_job`` is a plain function callable both directly (inline queue) and
as the Celery task ``process_job_task``. Each step opens a fresh DB session so
the API always observes the latest stage/progress.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta

from app.config import get_settings
from app.core.models import JobStage, JobStatus
from app.database import SessionLocal, utcnow
from app.models.db import Job
from app.storage import audio_key, get_storage, source_key
from app.worker.celery_app import celery_app
from app.worker.serialization import segments_to_json

log = logging.getLogger(__name__)


def _load_job(job_id: str) -> Job | None:
    db = SessionLocal()
    try:
        return db.get(Job, job_id)
    finally:
        db.close()


def _update_job(job_id: str, **fields: object) -> bool:
    """Apply ``fields`` to the job in a fresh session and commit."""
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return False
        for key, value in fields.items():
            setattr(job, key, value)
        db.commit()
        return True
    finally:
        db.close()


def process_job(job_id: str) -> None:
    """Run the full pipeline for ``job_id``; failures mark the job ``failed``."""
    try:
        _process_job(job_id)
    except Exception as exc:
        log.exception("job %s failed", job_id)
        _update_job(job_id, status=JobStatus.FAILED.value, stage=None, error=str(exc)[:500])


def _process_job(job_id: str) -> None:
    # lazy import: core helpers are provided by the app.core package
    from app.core import (
        LLMConfig,
        build_initial_prompt,
        correct_transcript,
        extract_audio,
        get_backend,
        load_terms,
        preprocess_audio,
        segment_words,
    )

    settings = get_settings()
    storage = get_storage()

    job = _load_job(job_id)
    if job is None:
        log.warning("job %s not found; skipping", job_id)
        return
    ext = os.path.splitext(job.filename)[1].lower() or ".bin"
    source = source_key(job_id, ext)
    if not storage.exists(source):
        raise RuntimeError(f"source file missing for job {job_id}")
    source_path = storage.open_path(source)

    # 1. extracting
    _update_job(
        job_id,
        status=JobStatus.PROCESSING.value,
        stage=JobStage.EXTRACTING.value,
        progress=10.0,
    )
    audio_path = storage.writable_path(audio_key(job_id))
    extract_audio(source_path, audio_path, sample_rate=16000)

    # 1b. preprocessing (denoise / loudnorm) — chain into a distinct temp path
    if job.denoise_enabled or job.loudnorm_enabled:
        _update_job(job_id, stage=JobStage.PREPROCESSING.value, progress=25.0)
        final = preprocess_audio(
            audio_path,
            storage.writable_path(audio_key(job_id) + ".proc.wav"),
            denoise=bool(job.denoise_enabled),
            loudnorm=bool(job.loudnorm_enabled),
            prop_decrease=settings.noise_reduction_strength,
        )
        storage.save(final, audio_key(job_id))
    else:
        storage.save(audio_path, audio_key(job_id))

    # 2. transcribing
    _update_job(job_id, stage=JobStage.TRANSCRIBING.value, progress=40.0)
    terms = load_terms(settings.dictionary_path)
    prompt = build_initial_prompt(terms, settings.initial_prompt_max_chars)
    backend = get_backend(
        tier=job.tier or settings.tier,
        beam_size=settings.beam_size,
        temperature=settings.temperature,
        vad_enabled=settings.vad_enabled,
    )
    raw = backend.transcribe(
        storage.open_path(audio_key(job_id)), job.language or None, initial_prompt=prompt
    )
    _update_job(job_id, progress=70.0)

    # 3. segmenting
    _update_job(job_id, stage=JobStage.SEGMENTING.value, progress=85.0)
    segments = segment_words(raw.all_words(), raw.language, max_chars=settings.max_line_chars)

    # 3b. LLM correction (best-effort; never raises)
    if job.llm_correction_enabled:
        _update_job(job_id, progress=90.0)
        llm_cfg = LLMConfig(
            provider=settings.llm_provider,
            model=settings.llm_model,
            url=settings.ollama_url,
            api_key=settings.llm_api_key,
            timeout_seconds=settings.llm_timeout_seconds,
        )
        segments = correct_transcript(segments, config=llm_cfg, dictionary_terms=terms)
    _update_job(job_id, progress=95.0)

    # 4. done
    now = utcnow()
    _update_job(
        job_id,
        status=JobStatus.DONE.value,
        stage=None,
        progress=100.0,
        segments_json=segments_to_json(segments),
        language=raw.language,
        completed_at=now,
        expires_at=now + timedelta(hours=settings.ttl_hours),
    )


process_job_task = celery_app.task(process_job)
