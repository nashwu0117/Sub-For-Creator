"""Tests for the Celery worker: queue topology, GPU affinity, settings parsing."""

from __future__ import annotations

import os

from app.config import get_settings, reset_settings
from app.worker.celery_app import _apply_gpu_affinity, celery_app


def _restore_env(key: str, original: str | None) -> None:
    if original is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = original


# ---------------------------------------------------------------- queue topology


def test_task_routes_map_to_queues():
    routes = celery_app.conf.task_routes
    assert routes["app.worker.tasks.process_job_task"]["queue"] == "transcribe"
    assert routes["app.worker.render_tasks.render_job"]["queue"] == "render"
    assert routes["app.worker.cleanup.cleanup_expired_jobs"]["queue"] == "celery"


def test_acks_late_and_prefetch_multiplier():
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.worker_prefetch_multiplier == 1


def test_render_tasks_included():
    assert "app.worker.render_tasks" in celery_app.conf.include


# ---------------------------------------------------------------- GPU affinity


def test_gpu_index_env_parsing(monkeypatch):
    monkeypatch.setenv("SFC_GPU_INDEX", "2")
    reset_settings()
    try:
        assert get_settings().gpu_index == 2
    finally:
        reset_settings()


def test_gpu_index_default_none(monkeypatch):
    monkeypatch.delenv("SFC_GPU_INDEX", raising=False)
    reset_settings()
    try:
        assert get_settings().gpu_index is None
    finally:
        reset_settings()


def test_gpu_index_empty_string_is_none(monkeypatch):
    monkeypatch.setenv("SFC_GPU_INDEX", "")
    reset_settings()
    try:
        assert get_settings().gpu_index is None
    finally:
        reset_settings()


def test_gpu_affinity_sets_cuda_visible_devices(monkeypatch):
    monkeypatch.setenv("SFC_GPU_INDEX", "1")
    reset_settings()
    original = os.environ.get("CUDA_VISIBLE_DEVICES")
    try:
        _apply_gpu_affinity()
        assert os.environ.get("CUDA_VISIBLE_DEVICES") == "1"
    finally:
        _restore_env("CUDA_VISIBLE_DEVICES", original)
        reset_settings()


def test_gpu_affinity_noop_when_unset(monkeypatch):
    monkeypatch.delenv("SFC_GPU_INDEX", raising=False)
    reset_settings()
    original = os.environ.get("CUDA_VISIBLE_DEVICES")
    try:
        _apply_gpu_affinity()
        assert os.environ.get("CUDA_VISIBLE_DEVICES") == original
    finally:
        _restore_env("CUDA_VISIBLE_DEVICES", original)
        reset_settings()


def test_gpu_affinity_ignores_negative_index(monkeypatch):
    monkeypatch.setenv("SFC_GPU_INDEX", "-1")
    reset_settings()
    original = os.environ.get("CUDA_VISIBLE_DEVICES")
    try:
        _apply_gpu_affinity()
        assert os.environ.get("CUDA_VISIBLE_DEVICES") == original
    finally:
        _restore_env("CUDA_VISIBLE_DEVICES", original)
        reset_settings()


# ---------------------------------------------------------------- queue settings


def test_queue_name_settings(monkeypatch):
    monkeypatch.setenv("SFC_TRANSCRIBE_QUEUE", "asr")
    monkeypatch.setenv("SFC_RENDER_QUEUE", "burn")
    reset_settings()
    try:
        settings = get_settings()
        assert settings.transcribe_queue == "asr"
        assert settings.render_queue == "burn"
        assert settings.default_queue == "celery"
    finally:
        reset_settings()
