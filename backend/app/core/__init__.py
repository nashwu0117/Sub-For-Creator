"""Core transcription engine: audio extraction, ASR backends, segmentation."""

from .asr import (
    ASRBackend,
    FasterWhisperBackend,
    MockBackend,
    WhisperXBackend,
    get_backend,
)
from .audio import extract_audio, probe_duration, probe_media
from .exceptions import (
    ASRError,
    AudioExtractionError,
    ExportError,
    JobNotFoundError,
    JobNotReadyError,
    MediaProcessingError,
    QuotaExceededError,
    RenderError,
    SegmentationError,
    SFCError,
    UnsupportedFormatError,
)
from .models import JobStage, JobStatus, Segment, TranscriptionResult, Word
from .segmenter import segment_words

__all__ = [
    "ASRBackend",
    "ASRError",
    "AudioExtractionError",
    "ExportError",
    "FasterWhisperBackend",
    "JobNotFoundError",
    "JobNotReadyError",
    "JobStage",
    "JobStatus",
    "MediaProcessingError",
    "MockBackend",
    "QuotaExceededError",
    "RenderError",
    "Segment",
    "SegmentationError",
    "SFCError",
    "TranscriptionResult",
    "UnsupportedFormatError",
    "WhisperXBackend",
    "Word",
    "extract_audio",
    "get_backend",
    "probe_duration",
    "probe_media",
    "segment_words",
]
