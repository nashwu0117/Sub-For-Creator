"""Test fixtures: env pinned BEFORE any app import, TestClient, settings overrides.

The whole suite runs against a throwaway sqlite DB + tmp storage dir with the
inline queue and the mock ASR backend — no redis, no GPU, no real model.
"""

from __future__ import annotations

import os
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="sfc-test-")

os.environ["SFC_DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["SFC_UPLOAD_DIR"] = os.path.join(_TMP, "storage")
os.environ["SFC_QUEUE_BACKEND"] = "inline"
os.environ["SFC_MAX_UPLOAD_MB"] = "10"
os.environ["SFC_MAX_DURATION_MIN"] = "60"
os.environ["SFC_DAILY_SECONDS_PER_SESSION"] = "60"
os.environ["SFC_UPLOAD_RATE_LIMIT"] = "1000"
os.environ["SFC_MAX_QUEUE"] = "50"
os.environ["SFC_TTL_HOURS"] = "48"
os.environ["SFC_MAX_LINE_CHARS"] = "16"

from fastapi.testclient import TestClient  # noqa: E402

from app.api.limits import reset_rate_limits  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
def mock_asr(monkeypatch):
    """Pin the deterministic mock ASR backend for this test."""
    monkeypatch.setenv("SFC_ASR_BACKEND", "mock")


@pytest.fixture(autouse=True)
def _isolated_state():
    """Reset rate-limit state and settings cache around every test."""
    reset_rate_limits()
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def override_settings(monkeypatch):
    """Apply SFC_* env overrides for one test (restored automatically)."""

    def _apply(**kwargs):
        for key, value in kwargs.items():
            monkeypatch.setenv(f"SFC_{key.upper()}", str(value))
        get_settings.cache_clear()

    yield _apply
    get_settings.cache_clear()
