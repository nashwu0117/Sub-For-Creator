"""Shared test helpers: media fixtures and API interaction utilities."""

from __future__ import annotations

import os
import shutil
import subprocess
import time

import pytest


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def make_wav(path: str, seconds: float = 2.0) -> str:
    """Generate a sine-wave WAV via ffmpeg lavfi (skips when ffmpeg is absent)."""
    if _ffmpeg() is None:
        pytest.skip("ffmpeg not installed")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-ar", "16000", "-ac", "1",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return str(path)


def make_video(path: str, seconds: float = 1.0) -> str:
    """Generate a tiny H.264+AAC MP4 via ffmpeg lavfi (skips when ffmpeg is absent)."""
    if _ffmpeg() is None:
        pytest.skip("ffmpeg not installed")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440",
            "-t", str(seconds),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return str(path)


def upload(
    client,
    path: str,
    token: str = "test-token",
    language: str | None = None,
    options: str | None = None,
):
    """POST /api/jobs with a file and optional form fields."""
    with open(path, "rb") as fh:
        files = {"file": (os.path.basename(path), fh, "application/octet-stream")}
        data: dict = {}
        if language is not None:
            data["language"] = language
        if options is not None:
            data["options"] = options
        return client.post(
            "/api/jobs", files=files, data=data, headers={"X-Session-Token": token}
        )


def wait_done(client, job_id: str, token: str = "test-token", max_iters: int = 100) -> dict:
    """Poll GET /api/jobs/{id} until the job is done; fail otherwise."""
    body: dict | None = None
    for _ in range(max_iters):
        resp = client.get(f"/api/jobs/{job_id}", headers={"X-Session-Token": token})
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] == "done":
            return body
        time.sleep(0.02)
    pytest.fail(f"job {job_id} did not finish; last status: {body and body['status']}")
