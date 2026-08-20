"""Tests for the render Celery task (ffmpeg burn-in moved off the API process)."""

from __future__ import annotations

import json
import shutil
import uuid

import pytest

from app.database import SessionLocal
from app.models.db import Job
from app.storage import get_storage, render_key, source_key
from app.worker.render_tasks import _persist_render_error, render_job, render_task
from tests.helpers import make_video

pytestmark = pytest.mark.usefixtures("mock_asr")


def _seed_done_job() -> str:
    db = SessionLocal()
    job = Job(
        id=uuid.uuid4().hex,
        session_token="render-test",
        status="done",
        filename="seed.mp4",
        language="zh",
        model_size="large-v3",
        duration=1.0,
        segments_json=json.dumps(
            [
                {
                    "id": 0,
                    "start": 0.1,
                    "end": 0.6,
                    "text": "今天天氣真好",
                    "words": [
                        {"text": "今天", "start": 0.1, "end": 0.3},
                        {"text": "天氣", "start": 0.3, "end": 0.5},
                    ],
                }
            ],
            ensure_ascii=False,
        ),
    )
    db.add(job)
    db.commit()
    db.close()
    return job.id


def _render_params() -> dict:
    return {
        "font_size": 64,
        "font_color": "#FFFFFF",
        "outline_color": "#000000",
        "font_family": None,
        "karaoke": False,
        "position": "bottom",
    }


# ---------------------------------------------------------------- task wiring


def test_render_task_routed_to_render_queue():
    routes = render_task.app.conf.task_routes
    assert routes["app.worker.render_tasks.render_job"]["queue"] == "render"


def test_render_task_name():
    assert render_task.name == "app.worker.render_tasks.render_job"


# ---------------------------------------------------------------- pipeline


def test_render_job_runs_pipeline(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    video = make_video(tmp_path / "src.mp4")
    job_id = _seed_done_job()
    storage = get_storage()
    storage.save(video, source_key(job_id, ".mp4"))

    render_job(job_id, "mp4", _render_params())

    assert storage.exists(render_key(job_id, "burned.mp4"))
    assert not storage.exists(render_key(job_id, "burned.mp4.error"))


def test_render_error_marker_persisted():
    job_id = _seed_done_job()
    storage = get_storage()
    _persist_render_error(job_id, "mp4", "boom")
    key = render_key(job_id, "burned.mp4.error")
    assert storage.exists(key)
    with open(storage.open_path(key), encoding="utf-8") as fh:
        assert fh.read() == "boom"
