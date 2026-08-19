"""Media probing and audio extraction via FFmpeg/ffprobe.

All calls shell out to ffmpeg/ffprobe with captured output so error messages
surface the real stderr tail. No third-party media libraries are required.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from .exceptions import AudioExtractionError, MediaProcessingError, UnsupportedFormatError


def _require(binary: str) -> str:
    path = shutil.which(binary)
    if path is None:
        raise MediaProcessingError(
            f"{binary} not found; install ffmpeg to process media files"
        )
    return path


def _run(cmd: list[str], error_type, context: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        detail = stderr[-500:] if stderr else "no stderr output"
        raise error_type(f"{context}: {detail}")
    return proc


def probe_duration(path: str) -> float:
    """Return media duration in seconds, raising MediaProcessingError on failure."""
    ffprobe = _require("ffprobe")
    proc = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        MediaProcessingError,
        f"failed to probe duration of {path!r}",
    )
    try:
        return float(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise MediaProcessingError(
            f"could not parse duration from ffprobe output for {path!r}"
        ) from exc


def probe_media(path: str) -> dict:
    """Probe a media file and return a summary dict.

    Raises MediaProcessingError when the file is unreadable and
    UnsupportedFormatError when it has neither a video nor an audio stream.
    """
    ffprobe = _require("ffprobe")
    proc = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,duration",
            "-of",
            "json",
            path,
        ],
        MediaProcessingError,
        f"failed to probe media {path!r}",
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise MediaProcessingError(
            f"could not parse ffprobe JSON output for {path!r}"
        ) from exc

    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None and audio is None:
        raise UnsupportedFormatError(
            f"no decodable video or audio stream found in {path!r}"
        )

    fmt = data.get("format") or {}
    duration = float(fmt.get("duration") or 0.0)
    if not duration:
        stream_durations = [float(s["duration"]) for s in streams if s.get("duration")]
        if stream_durations:
            duration = stream_durations[0]

    primary = video or audio
    return {
        "duration": duration,
        "has_video": video is not None,
        "has_audio": audio is not None,
        "width": int(video["width"]) if video and video.get("width") is not None else None,
        "height": int(video["height"]) if video and video.get("height") is not None else None,
        "container": fmt.get("format_name") or "",
        "codec": primary.get("codec_name") if primary else None,
    }


def extract_audio(input_path: str, output_path: str, sample_rate: int = 16000) -> None:
    """Extract a 16kHz mono WAV track from the input media.

    Overwrites an existing output file. Raises AudioExtractionError on failure.
    """
    ffmpeg = _require("ffmpeg")
    _run(
        [
            ffmpeg,
            "-y",
            "-i",
            input_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            output_path,
        ],
        AudioExtractionError,
        f"audio extraction failed for {input_path!r}",
    )
