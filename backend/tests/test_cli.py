"""End-to-end tests for the standalone CLI (cli/subforcreator.py).

Each test runs the CLI as a subprocess from the repo root with the --mock
backend so no GPU / network is required.
"""

import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "cli" / "subforcreator.py"

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(CLI), *map(str, args)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.fixture(scope="module")
def wav_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "input.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(path)],
        check=True,
        capture_output=True,
    )
    return path


@pytest.fixture(scope="module")
def mp4_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "input.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def test_mock_srt_export(wav_file, tmp_path):
    out = tmp_path / "out.srt"
    result = run_cli(wav_file, "--mock", "--lang", "zh", "-o", out)
    assert result.returncode == 0, result.stderr
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "-->" in content
    assert "1" in content


def test_mock_ass_karaoke(wav_file, tmp_path):
    out = tmp_path / "out.ass"
    result = run_cli(wav_file, "--mock", "--format", "ass", "--karaoke", "-o", out)
    assert result.returncode == 0, result.stderr
    content = out.read_text(encoding="utf-8")
    assert "[Events]" in content
    assert "{\\k" in content


def test_mock_fcpxml(wav_file, tmp_path):
    out = tmp_path / "out.fcpxml"
    result = run_cli(wav_file, "--mock", "--format", "fcpxml", "-o", out)
    assert result.returncode == 0, result.stderr
    ET.fromstring(out.read_text(encoding="utf-8"))  # must be well-formed XML


def test_missing_input(tmp_path):
    result = run_cli(tmp_path / "does-not-exist.mp4", "--mock")
    assert result.returncode == 1
    assert result.stderr.strip()


def test_version():
    result = run_cli("--version")
    assert result.returncode == 0
    assert re.search(r"\d+\.\d+\.\d+", result.stdout)


def test_burn(mp4_file, tmp_path):
    out = tmp_path / "burned.mp4"
    result = run_cli(mp4_file, "--mock", "--burn", "-o", out, "--font-size", "48")
    assert result.returncode == 0, result.stderr
    assert out.exists()
    assert out.stat().st_size > 0
