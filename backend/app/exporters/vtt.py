"""WebVTT subtitle export.

Cues carry no index numbers; timestamps use ``HH:MM:SS.mmm`` with a dot
decimal separator. Newlines inside segment text are collapsed to a single
space so each cue stays on one line.
"""

from __future__ import annotations

from ..core.models import TranscriptionResult


def _format_timestamp(seconds: float) -> str:
    """Format seconds as ``HH:MM:SS.mmm`` (dot, milliseconds)."""
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def export_vtt(result: TranscriptionResult) -> str:
    """Serialize a TranscriptionResult as a WebVTT document."""
    out = ["WEBVTT\n\n"]
    for seg in result.segments:
        text = seg.text.replace("\r\n", "\n").replace("\n", " ")
        out.append(
            f"{_format_timestamp(seg.start)} --> {_format_timestamp(seg.end)}\n"
            f"{text}\n\n"
        )
    return "".join(out)
