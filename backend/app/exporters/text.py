"""Plain-text export: one segment per line, no timestamps.

With ``include_punctuation=False``, CJK and Latin punctuation is removed
from the text via a ``str.translate`` table and whitespace runs are
collapsed, yielding clean subtitle lines for social-media captions.
"""

from __future__ import annotations

from ..core.models import TranscriptionResult

# CJK + Latin punctuation removed when include_punctuation=False.
_PUNCTUATION = "。，、！？；：,.!?;:…“”‘’（）()「」『』·"

# str.translate: mapping a codepoint to None deletes the character.
_PUNCTUATION_TABLE = str.maketrans("", "", _PUNCTUATION)


def export_text(result: TranscriptionResult, include_punctuation: bool = True) -> str:
    """Serialize segments as plain text, one line per segment."""
    lines: list[str] = []
    for seg in result.segments:
        text = seg.text.replace("\r\n", "\n").replace("\n", " ")
        if not include_punctuation:
            text = text.translate(_PUNCTUATION_TABLE)
        lines.append(" ".join(text.split()))
    return "\n".join(lines) + "\n"
