"""Core transcription engine: audio extraction, ASR backends, segmentation."""

from .asr import (
    ASRBackend,
    FasterWhisperBackend,
    MockBackend,
    WhisperXBackend,
    get_backend,
    resolve_asr_config,
)
from .audio import extract_audio, probe_duration, probe_media
from .dictionary import (
    add_terms,
    build_initial_prompt,
    load_terms,
    remove_term,
)
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
from .llm_correction import LLMConfig, correct_transcript
from .models import JobStage, JobStatus, Segment, TranscriptionResult, Word
from .preprocess import denoise_audio, normalize_loudness, preprocess_audio
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
    "LLMConfig",
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
    "add_terms",
    "build_initial_prompt",
    "correct_transcript",
    "denoise_audio",
    "extract_audio",
    "get_backend",
    "load_terms",
    "normalize_loudness",
    "preprocess_audio",
    "probe_duration",
    "probe_media",
    "remove_term",
    "resolve_asr_config",
    "segment_words",
]
