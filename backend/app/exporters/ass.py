"""Advanced SubStation Alpha (ASS) subtitle export.

Emits a complete ASS document: [Script Info], [V4+ Styles] and [Events].
Timestamps use ``H:MM:SS.cc`` (centiseconds, hours not zero-padded).
With ``karaoke=True`` each word is prefixed by an inline ``{\\k<cs>}`` tag
(ASS \\k durations are in centiseconds).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.exceptions import ExportError
from ..core.models import Segment, TranscriptionResult

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")

# Field order of the [V4+ Styles] Format line; the Style: row below must
# stay in sync with this list.
_STYLE_FORMAT = (
    "Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
    "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, "
    "Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, "
    "Encoding"
)


@dataclass
class AssStyle:
    """Style descriptor for ASS export (plain dataclass, passed by the API)."""

    style_name: str = "Default"
    font_name: str = "Noto Sans CJK TC"
    font_size: int = 64
    primary_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    back_color: str = "#000000"
    outline: int = 2
    shadow: int = 1
    bold: bool = False
    italic: bool = False
    alignment: int = 2  # ASS alignment: 2 = bottom-center, 8 = top-center
    margin_l: int = 40
    margin_r: int = 40
    margin_v: int = 40
    fade: int = 0  # ms; 0 disables the \\fad tag


def ass_color(hex_color: str) -> str:
    """Convert ``#RRGGBB`` to ASS ``&H00BBGGRR`` (alpha 00, BGR order).

    Raises ExportError when the input is not a valid ``#RRGGBB`` hex color.
    """
    if not isinstance(hex_color, str) or not _HEX_COLOR.match(hex_color):
        raise ExportError(f"Invalid ASS color {hex_color!r}: expected #RRGGBB")
    rgb = hex_color[1:]
    return f"&H00{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}".upper()


def _format_timestamp(seconds: float) -> str:
    """Format seconds as ``H:MM:SS.cc`` (centiseconds, hours not padded)."""
    total_cs = int(round(seconds * 100))
    hours, rem = divmod(total_cs, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, centis = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _escape(text: str) -> str:
    """Escape text for ASS: ``\\N`` for newlines, ``\\{``/``\\}`` for braces."""
    return text.replace("\n", "\\N").replace("{", "\\{").replace("}", "\\}")


def _dialogue_text(seg: Segment, karaoke: bool, fade: int) -> str:
    """Build the Text field of a Dialogue line for one segment."""
    prefix = f"{{\\fad({fade},{fade})}}" if fade > 0 else ""
    if karaoke and seg.words:
        parts: list[str] = [prefix] if prefix else []
        for word in seg.words:
            duration_cs = max(1, int(round((word.end - word.start) * 100)))
            parts.append(f"{{\\k{duration_cs}}}{_escape(word.text)}")
        return "".join(parts)
    return prefix + _escape(seg.text)


def export_ass(
    result: TranscriptionResult,
    style: AssStyle | None = None,
    karaoke: bool = False,
) -> str:
    """Serialize a TranscriptionResult as a full ASS document."""
    style = style or AssStyle()
    primary = ass_color(style.primary_color)
    outline = ass_color(style.outline_color)
    back = ass_color(style.back_color)

    style_row = ",".join(
        [
            style.style_name,
            style.font_name,
            str(style.font_size),
            primary,
            primary,  # SecondaryColour mirrors PrimaryColour
            outline,
            back,
            str(int(style.bold)),
            str(int(style.italic)),
            "0",  # Underline
            "0",  # StrikeOut
            "100",  # ScaleX
            "100",  # ScaleY
            "0",  # Spacing
            "0",  # Angle
            "1",  # BorderStyle: outline + shadow
            str(style.outline),
            str(style.shadow),
            str(style.alignment),
            str(style.margin_l),
            str(style.margin_r),
            str(style.margin_v),
            "1",  # Encoding
        ]
    )

    lines = [
        "[Script Info]",
        "Title: Sub for Creator",
        "ScriptType: v4.00+",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        f"Format: {_STYLE_FORMAT}",
        f"Style: {style_row}",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for seg in result.segments:
        lines.append(
            f"Dialogue: 0,{_format_timestamp(seg.start)},{_format_timestamp(seg.end)},"
            f"{style.style_name},,0,0,0,,{_dialogue_text(seg, karaoke, style.fade)}"
        )
    return "\n".join(lines) + "\n"
