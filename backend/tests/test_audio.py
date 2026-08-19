"""Tests for audio probing and extraction (skipped when ffmpeg is absent)."""

import json
import shutil
import subprocess

import pytest

from app.core.audio import extract_audio, probe_duration, probe_media
from app.core.exceptions import AudioExtractionError, MediaProcessingError, UnsupportedFormatError

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)


def run_ffmpeg(args: list[str]) -> str:
    cmd = ["ffmpeg", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-500:]
    return " ".join(cmd)


@pytest.fixture(scope="module")
def sine_wav(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "sine.wav"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(path),
        ]
    )
    return str(path)


def ffprobe_streams(path: str) -> list[dict]:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,sample_rate,channels",
            "-of",
            "json",
            path,
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["streams"]


def test_probe_duration(sine_wav):
    duration = probe_duration(sine_wav)
    assert 0.95 <= duration <= 1.05


def test_probe_duration_missing_file(tmp_path):
    with pytest.raises(MediaProcessingError):
        probe_duration(str(tmp_path / "nope.mp4"))


def test_probe_media_audio_flags(sine_wav):
    info = probe_media(sine_wav)
    assert info["has_audio"] is True
    assert info["has_video"] is False
    assert 0.95 <= info["duration"] <= 1.05
    assert info["codec"] is not None


def test_probe_media_video_flags(tmp_path):
    path = str(tmp_path / "clip.mp4")
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=128x72:rate=15",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            path,
        ]
    )
    info = probe_media(path)
    assert info["has_video"] is True
    assert info["has_audio"] is True
    assert info["width"] == 128
    assert info["height"] == 72
    assert 0.9 <= info["duration"] <= 1.1
    assert info["container"]
    assert info["codec"] is not None


def test_probe_media_unreadable(tmp_path):
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"\x00\x01\x02 this is not a media file")
    with pytest.raises((MediaProcessingError, UnsupportedFormatError)):
        probe_media(str(bad))


def test_probe_media_missing_file(tmp_path):
    with pytest.raises(MediaProcessingError):
        probe_media(str(tmp_path / "nope.mp4"))


def test_extract_audio_16k_mono(sine_wav, tmp_path):
    out = str(tmp_path / "audio.wav")
    extract_audio(sine_wav, out, sample_rate=16000)
    streams = ffprobe_streams(out)
    assert len(streams) == 1
    assert streams[0]["codec_type"] == "audio"
    assert int(streams[0]["sample_rate"]) == 16000
    assert streams[0]["channels"] == 1


def test_extract_audio_overwrites(sine_wav, tmp_path):
    out = str(tmp_path / "audio.wav")
    extract_audio(sine_wav, out, sample_rate=16000)
    first_mtime = (tmp_path / "audio.wav").stat().st_mtime
    extract_audio(sine_wav, out, sample_rate=16000)
    assert (tmp_path / "audio.wav").exists()
    assert (tmp_path / "audio.wav").stat().st_mtime >= first_mtime


def test_extract_audio_missing_input(tmp_path):
    out = str(tmp_path / "out.wav")
    with pytest.raises((AudioExtractionError, MediaProcessingError)):
        extract_audio(str(tmp_path / "missing.mp4"), out)
