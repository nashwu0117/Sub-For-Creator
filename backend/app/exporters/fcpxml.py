"""Final Cut Pro XML (FCPXML 1.10) export for title clips.

Builds a document with one ``<title>`` clip per segment over an
``<asset-clip>`` of the source media. Durations are emitted as ``{value}s``
strings; zero/negative durations are clamped to a 0.04s minimum, which
FCPXML rejects below.
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET

from ..core.exceptions import ExportError
from ..core.models import TranscriptionResult

_MIN_DURATION = 0.04  # seconds; FCPXML rejects zero/negative durations


def _seconds(value: float) -> str:
    """Format seconds as ``12.5s``, trimming float noise (no min clamp)."""
    return f"{max(0.0, value):.3f}".rstrip("0").rstrip(".") + "s"


def _duration(value: float) -> str:
    """Format a duration with a 0.04s minimum."""
    return _seconds(max(_MIN_DURATION, value))


def export_fcpxml(
    result: TranscriptionResult,
    media_name: str = "video",
    frame_rate: int = 30,
    width: int = 1920,
    height: int = 1080,
    font_size: int = 96,
) -> str:
    """Serialize a TranscriptionResult as an FCPXML 1.10 document."""
    if frame_rate <= 0 or width <= 0 or height <= 0 or font_size <= 0:
        raise ExportError("frame_rate, width, height and font_size must be positive")

    total = result.media_duration
    if total is None:
        total = result.segments[-1].end if result.segments else 0.0

    root = ET.Element("fcpxml", version="1.10")
    resources = ET.SubElement(root, "resources")
    ET.SubElement(
        resources,
        "format",
        id="r0",
        name="FFVideoFormat1080p30",
        frameDuration=f"100/{frame_rate * 100}s",
        width=str(width),
        height=str(height),
    )
    ET.SubElement(
        resources,
        "asset",
        id="r1",
        name=media_name,
        src=f"file:///{media_name}",
        start="0s",
        duration=_duration(total),
        format="r0",
    )
    text_def = ET.SubElement(resources, "def", id="r2")
    text_style_def = ET.SubElement(text_def, "text-style-def", id="r3")
    ET.SubElement(
        text_style_def,
        "text-style",
        font="Helvetica",
        fontSize=str(font_size),
        fontColor="1 1 1 1",
    )

    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", name="Sub for Creator")
    project = ET.SubElement(event, "project", name="Subs", uid=str(uuid.uuid4()))
    sequence = ET.SubElement(project, "sequence", duration=_duration(total), format="r0")
    spine = ET.SubElement(sequence, "spine")
    ET.SubElement(
        spine,
        "asset-clip",
        ref="r1",
        offset="0s",
        duration=_duration(total),
        format="r0",
    )
    for seg in result.segments:
        title = ET.SubElement(
            spine,
            "title",
            ref="r2",
            offset=_seconds(seg.start),
            duration=_duration(seg.duration()),
            start="0s",
        )
        text = ET.SubElement(title, "text")
        text_style = ET.SubElement(text, "text-style", ref="r3")
        text_style.text = seg.text  # ElementTree escapes XML entities

    declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'
    return declaration + ET.tostring(root, encoding="unicode")
