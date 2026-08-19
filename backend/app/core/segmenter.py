"""Rule-based segmentation of word-level timestamps into subtitle lines.

Splitting rules, evaluated in order at each word boundary:
1. End-of-sentence punctuation (。！？!?… variants): split after the word.
2. Pause: gap between the previous word's end and the current word's start
   >= pause_threshold seconds.
3. Length: current line character count (excluding whitespace) >= max_chars.
   Prefer a soft boundary (after ，、；：,.!?;。 punctuation) seen since the
   last split; otherwise fall back to the largest word prefix that still fits
   under max_chars. Words are never split in half — a single overlong English
   word stays on its own line.

Groups are built greedily, then sanitized: whitespace is trimmed/collapsed,
punctuation-only or empty lines are dropped, and any non-final line shorter
than `min_segment_duration` is merged into the following line (its start is
extended backward) so very short flashes are absorbed instead of dropped.
The final line is always kept. Segment ids are reassigned so they are
contiguous starting at 0, and every segment guarantees start < end.
"""

from __future__ import annotations

from .exceptions import SegmentationError
from .models import Segment, Word

CJK_LANGS = {"zh", "ja", "ko"}
DEFAULT_MAX_CHARS = {"zh": 16, "ja": 20, "ko": 20, "en": 40}

#: punctuation that ends a sentence — hard split after the word carrying it
END_PUNCT = set("。！？!?…")
#: punctuation that marks a good (soft) split point for the length rule
SOFT_PUNCT = set("，、；：,.!?;。")
#: characters that may appear in an otherwise-punctuation-only line (dropped)
PUNCT_ONLY = set("。，、；：,.!?;… \u3000")


def _char_len(text: str) -> int:
    """Character count excluding whitespace (used by the max_chars rule)."""
    return len("".join(text.split()))


def _last_char(text: str) -> str:
    t = text.rstrip()
    return t[-1] if t else ""


def _clean(text: str) -> str:
    """Collapse runs of whitespace to single spaces and strip the result."""
    return " ".join(text.split())


def _make_text(words: list[Word], lang: str) -> str:
    sep = "" if lang in CJK_LANGS else " "
    return _clean(sep.join(w.text for w in words))


def _forced_split(current: list[Word], max_chars: int, is_cjk: bool) -> int:
    """Index to split `current` after when no soft boundary is available.

    Prefers the largest prefix whose character count fits under `max_chars`;
    for non-CJK text a whitespace-adjacent word boundary is preferred when one
    fits. Never splits a word in half: an overlong word stays on its own line.
    """
    total = sum(_char_len(w.text) for w in current)
    if total <= max_chars:
        return len(current) - 1
    acc = 0
    best = 0
    ws_best = None
    for j in range(len(current) - 1):
        acc += _char_len(current[j].text)
        if acc > max_chars:
            break
        best = j
        if not is_cjk and current[j + 1].text[:1].isspace():
            ws_best = j
    return ws_best if ws_best is not None else best


def _build_segments(
    groups: list[list[Word]], lang: str, min_segment_duration: float
) -> list[Segment]:
    raw: list[Segment] = []
    for group in groups:
        start = group[0].start
        end = group[-1].end
        if end <= start:
            end = start + 0.1
        text = _make_text(group, lang)
        if not text or all(c in PUNCT_ONLY for c in text):
            continue
        words = [Word(text=_clean(w.text), start=w.start, end=w.end) for w in group]
        raw.append(Segment(id=0, start=start, end=end, text=text, words=words))

    merged: list[Segment] = []
    for i, seg in enumerate(raw):
        if i < len(raw) - 1 and seg.end - seg.start < min_segment_duration:
            nxt = raw[i + 1]
            nxt.words = seg.words + nxt.words
            nxt.text = _make_text(nxt.words, lang)
            nxt.start = min(nxt.start, seg.start)
            continue
        merged.append(seg)

    for i, seg in enumerate(merged):
        seg.id = i
        if seg.start < 0:
            seg.start = 0.0
        if seg.end <= seg.start:
            seg.end = seg.start + 0.1
    return merged


def segment_words(
    words: list[Word],
    lang: str = "zh",
    max_chars: int | None = None,
    pause_threshold: float = 0.3,
    min_segment_duration: float = 0.3,
) -> list[Segment]:
    """Split a flattened word list into readable subtitle segments.

    When `max_chars` is None it defaults per language: zh=16, ja=20, ko=20,
    en=40, anything else=40. Raises SegmentationError on an empty word list.
    """
    if not words:
        raise SegmentationError("cannot segment an empty word list")
    if max_chars is None:
        max_chars = DEFAULT_MAX_CHARS.get(lang, 40)

    is_cjk = lang in CJK_LANGS

    normalized: list[Word] = []
    for word in words:
        if not _clean(word.text):
            continue
        normalized.append(
            Word(text=word.text, start=max(0.0, word.start), end=max(0.0, word.end))
        )
    if not normalized:
        raise SegmentationError("no usable words after sanitization")

    groups: list[list[Word]] = []
    current: list[Word] = []
    chars = 0
    soft_idx: int | None = None

    for i, word in enumerate(normalized):
        current.append(word)
        chars += _char_len(word.text)
        if _last_char(word.text) in SOFT_PUNCT:
            soft_idx = len(current) - 1

        split_at = None
        if _last_char(word.text) in END_PUNCT or (
            i + 1 < len(normalized) and normalized[i + 1].start - word.end >= pause_threshold
        ):
            split_at = len(current) - 1
        elif chars >= max_chars:
            if soft_idx is not None:
                split_at = soft_idx
            else:
                split_at = _forced_split(current, max_chars, is_cjk)

        if split_at is not None:
            groups.append(current[: split_at + 1])
            current = current[split_at + 1 :]
            chars = sum(_char_len(w.text) for w in current)
            soft_idx = None

    if current:
        groups.append(current)

    return _build_segments(groups, lang, min_segment_duration)
