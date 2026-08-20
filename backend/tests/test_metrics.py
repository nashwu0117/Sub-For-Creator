"""Tests for the Prometheus /api/metrics endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from app.api import metrics as metrics_router
from app.database import SessionLocal
from app.main import create_app
from app.models.db import Job

pytestmark = pytest.mark.usefixtures("mock_asr")

REQUIRED_METRICS = (
    "sfc_jobs_total",
    "sfc_queue_depth",
    "sfc_workers_concurrency",
    "sfc_storage_bytes",
    "sfc_storage_objects",
    "sfc_gpu_utilization_percent",
    "sfc_gpu_memory_used_bytes",
    "sfc_gpu_memory_total_bytes",
    "sfc_asr_backend",
    "sfc_job_duration_seconds",
)


@pytest.fixture
def client():
    """App with the metrics router registered (mirrors the main.py wiring note)."""
    app = create_app()
    app.include_router(metrics_router.router, prefix="/api")
    with TestClient(app) as c:
        yield c


def _families(text: str) -> dict[str, object]:
    return {fam.name: fam for fam in text_string_to_metric_families(text)}


def test_metrics_endpoint_returns_valid_prometheus_text(client):
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    families = _families(resp.text)
    for name in REQUIRED_METRICS:
        assert name in families, f"missing metric {name}"


def test_metrics_reflects_seeded_job(client):
    db = SessionLocal()
    db.add(
        Job(
            id="metrics-test-job",
            session_token="metrics-token",
            status="queued",
            filename="seed.mp4",
            language="zh",
            model_size="large-v3",
            duration=2.0,
        )
    )
    db.commit()
    db.close()

    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    families = _families(resp.text)

    jobs = families["sfc_jobs_total"]
    by_status = {s.labels["status"]: s.value for s in jobs.samples}
    assert by_status.get("queued", 0) >= 1

    queue_depth = next(s.value for s in families["sfc_queue_depth"].samples)
    assert queue_depth >= 1

    asr = {s.labels["backend"]: s.value for s in families["sfc_asr_backend"].samples}
    assert sum(asr.values()) == 1, "exactly one ASR backend must be active"


def test_metrics_disabled_returns_404(client, override_settings):
    override_settings(metrics_enabled=False)
    resp = client.get("/api/metrics")
    assert resp.status_code == 404
