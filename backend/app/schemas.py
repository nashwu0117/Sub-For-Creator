"""Pydantic request/response models for the API layer."""

from __future__ import annotations

from pydantic import BaseModel, model_validator


class SegmentWordIn(BaseModel):
    """A word inside a PUT /subtitles segment; ``text`` or ``word`` accepted."""

    text: str | None = None
    word: str | None = None
    start: float
    end: float


class SegmentIn(BaseModel):
    """One edited subtitle segment from PUT /subtitles."""

    id: int
    start: float
    end: float
    text: str
    words: list[SegmentWordIn] | None = None

    @model_validator(mode="after")
    def _check_ordering(self) -> SegmentIn:
        if self.end <= self.start:
            raise ValueError("segment end must be greater than start")
        return self


class SubtitlesUpdate(BaseModel):
    """PUT /jobs/{job_id}/subtitles body."""

    segments: list[SegmentIn]

    @model_validator(mode="after")
    def _check_unique_ids(self) -> SubtitlesUpdate:
        ids = [seg.id for seg in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError("segment ids must be unique")
        return self


class JobOptions(BaseModel):
    """Optional JSON ``options`` field of the upload form."""

    model_size: str | None = None
    max_line_chars: int | None = None
    tier: str | None = None
    denoise_enabled: bool | None = None
    loudnorm_enabled: bool | None = None
    llm_correction_enabled: bool | None = None


class DictionaryAdd(BaseModel):
    """POST /api/dictionary body: terms to add."""

    terms: list[str]


class DictionaryRemove(BaseModel):
    """DELETE /api/dictionary body: the term to remove."""

    term: str
