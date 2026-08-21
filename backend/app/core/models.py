"""Shared domain models — single source of truth for the whole project.

Consumed by:
- backend/app/core (asr, segmenter)
- backend/app/exporters
- backend/app/api, backend/app/worker, backend/app/models (db)
- cli/subforcreator.py

Keep this file stdlib-only (no pydantic/sqlalchemy imports).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class JobStatus(str, Enum):
    """Job lifecycle: queued -> processing -> done | failed ; done -> expired."""

    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    EXPIRED = "expired"


class JobStage(str, Enum):
    """Sub-stages of processing, used for progress display."""

    EXTRACTING = "extracting"
    PREPROCESSING = "preprocessing"
    TRANSCRIBING = "transcribing"
    SEGMENTING = "segmenting"
    RENDERING = "rendering"


@dataclass
class Word:
    text: str
    start: float  # seconds
    end: float  # seconds

    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Segment:
    id: int
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    x: float | None = None
    y: float | None = None

    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class TranscriptionResult:
    """Raw ASR output, before rule-based re-segmentation."""

    segments: list[Segment]
    language: str  # ISO 639-1, e.g. "zh", "en", "ja", "ko"
    language_probability: float | None = None
    media_duration: float | None = None  # seconds
    model_size: str = "large-v3"

    def all_words(self) -> list[Word]:
        """Flatten all words across segments (used as input to segmentation)."""
        words: list[Word] = []
        for seg in self.segments:
            if seg.words:
                words.extend(seg.words)
            else:
                # Some backends return text without word timestamps;
                # synthesize a single word covering the whole segment.
                words.append(Word(text=seg.text, start=seg.start, end=seg.end))
        return words
