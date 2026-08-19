"""Project-wide exceptions.

The API layer maps these to HTTP responses; the CLI maps them to exit code 1
with a friendly message. Never raise raw OSError/RuntimeError across layer
boundaries when a typed error exists here.
"""

from __future__ import annotations


class SFCError(Exception):
    """Base class for all project errors."""


class MediaProcessingError(SFCError):
    """FFmpeg/ffprobe failure or unreadable media."""


class UnsupportedFormatError(MediaProcessingError):
    """File has no decodable video/audio stream."""


class AudioExtractionError(MediaProcessingError):
    """Audio track extraction failed."""


class ASRError(SFCError):
    """Speech recognition backend failed."""


class SegmentationError(SFCError):
    """Segmentation step failed (should not happen in normal operation)."""


class ExportError(SFCError):
    """Output generation failed."""


class JobNotFoundError(SFCError):
    """Job id does not exist."""


class JobNotReadyError(SFCError):
    """Job is not in `done` state yet."""


class QuotaExceededError(SFCError):
    """Session hit a rate limit (size / duration / frequency / queue)."""


class RenderError(SFCError):
    """FFmpeg burn-in rendering failed."""
