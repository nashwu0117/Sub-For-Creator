"""ASR backend abstraction.

Backends implement the ASRBackend protocol and return a TranscriptionResult.
Heavy ML frameworks (whisperx, faster-whisper) are imported lazily inside
``transcribe`` so the rest of the app and the test suite never need them
installed; the mock backend needs neither a model nor ffmpeg.
"""

from __future__ import annotations

import logging
import os
from typing import Protocol

from .audio import probe_duration
from .exceptions import ASRError, MediaProcessingError
from .models import Segment, TranscriptionResult, Word

logger = logging.getLogger(__name__)

VALID_BACKENDS = ("whisperx", "faster-whisper", "mock")

#: deterministic mock sentences, one segment per sentence
MOCK_SENTENCES: dict[str, list[str]] = {
    "zh": ["今天天氣真好。", "我們一起去公園散步。", "字幕工具真方便。", "希望你能喜歡。"],
    "en": [
        "Hello everyone, welcome back.",
        "This is a subtitle tool.",
        "It works really very well.",
        "Enjoy your favorite videos.",
    ],
    "ja": [
        "今日はいい天気です。",
        "公園を散歩しましょう。",
        "字幕ツールは便利です。",
        "楽しんでください。",
    ],
    "ko": [
        "오늘 날씨가 좋아요.",
        "공원에서 산책해요.",
        "자막 도구가 편해요.",
        "좋아하길 바래요.",
    ],
}


class ASRBackend(Protocol):
    """Transcribe an audio file into word/segment timestamps."""

    def transcribe(self, audio_path: str, language: str | None = None) -> TranscriptionResult:
        ...


def _resolve_language(language: str | None) -> str | None:
    """Map None / '' / 'auto' to None (auto-detect); pass other codes through."""
    if language in (None, "", "auto"):
        return None
    return language


def _cuda_available() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except ImportError:
        return False


def _cjk_words(sentence: str) -> list[str]:
    """Split a CJK sentence into 4-6 character chunks (deterministic)."""
    chars = list(sentence)
    n_words = max(4, min(6, (len(chars) + 1) // 2))
    n_words = min(n_words, len(chars))
    base, rem = divmod(len(chars), n_words)
    words: list[str] = []
    idx = 0
    for k in range(n_words):
        size = base + (1 if k < rem else 0)
        words.append("".join(chars[idx : idx + size]))
        idx += size
    return words


class WhisperXBackend:
    """WhisperX transcription backend (lazy import; GPU-accelerated when available)."""

    def __init__(self, model_size: str | None = None):
        self.model_size = model_size or os.environ.get("SFC_WHISPERX_MODEL") or "large-v3"

    def transcribe(self, audio_path: str, language: str | None = None) -> TranscriptionResult:
        try:
            import whisperx
        except ImportError as exc:
            raise ASRError(
                "whisperx is not installed; install backend/requirements-gpu.txt "
                "to use the whisperx backend"
            ) from exc

        device = "cuda" if _cuda_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        model = whisperx.load_model(self.model_size, device=device, compute_type=compute_type)
        audio = whisperx.load_audio(audio_path)
        result = model.transcribe(audio, language=_resolve_language(language))

        language_out = _resolve_language(language) or result.get("language") or "unknown"
        # Word-level alignment is best-effort: fall back to segment timestamps.
        try:
            align_model, metadata = whisperx.load_align_model(
                language_code=language_out, device=device
            )
            result = whisperx.align(result["segments"], align_model, metadata, audio, device)
        except Exception as exc:  # noqa: BLE001 - alignment is optional
            logger.warning("whisperx alignment failed, keeping segment timestamps: %s", exc)

        segments = []
        for i, seg in enumerate(result["segments"]):
            words = [
                Word(text=w["word"], start=float(w["start"]), end=float(w["end"]))
                for w in (seg.get("words") or [])
                if w.get("start") is not None and w.get("end") is not None
            ]
            segments.append(
                Segment(
                    id=i,
                    start=float(seg["start"]),
                    end=float(seg["end"]),
                    text=str(seg["text"]).strip(),
                    words=words,
                )
            )
        media_duration = len(audio) / 16000.0 if audio.size else None
        return TranscriptionResult(
            segments=segments,
            language=language_out,
            media_duration=media_duration,
            model_size=self.model_size,
        )


class FasterWhisperBackend:
    """faster-whisper transcription backend (lazy import)."""

    def __init__(self, model_size: str = "large-v3"):
        self.model_size = model_size

    def transcribe(self, audio_path: str, language: str | None = None) -> TranscriptionResult:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ASRError(
                "faster-whisper is not installed; install backend/requirements.txt "
                "to use the faster-whisper backend"
            ) from exc

        device = "cuda" if _cuda_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        model = WhisperModel(self.model_size, device=device, compute_type=compute_type)
        segments_iter, info = model.transcribe(
            audio_path,
            language=_resolve_language(language),
            word_timestamps=True,
            vad_filter=True,
        )

        segments = []
        for i, seg in enumerate(segments_iter):
            words = [
                Word(text=word.word, start=word.start, end=word.end)
                for word in (seg.words or [])
                if word.start is not None and word.end is not None
            ]
            segments.append(
                Segment(id=i, start=seg.start, end=seg.end, text=seg.text.strip(), words=words)
            )
        language_out = info.language or _resolve_language(language) or "unknown"
        return TranscriptionResult(
            segments=segments,
            language=language_out,
            media_duration=info.duration,
            model_size=self.model_size,
        )


class MockBackend:
    """Deterministic fake ASR for tests and CI — no model, no ffmpeg required.

    Sentences are placed evenly across the media duration (probed via
    ``probe_duration``; falls back to 60s when probing fails). Each sentence
    becomes one segment with 4-6 words, split by characters for CJK languages
    and by spaces for English.
    """

    def __init__(self, model_size: str = "mock"):
        self.model_size = model_size

    def transcribe(self, audio_path: str, language: str | None = None) -> TranscriptionResult:
        lang = "zh" if language in (None, "", "auto") else language
        sentences = MOCK_SENTENCES.get(lang, MOCK_SENTENCES["zh"])
        try:
            duration = probe_duration(audio_path)
        except MediaProcessingError:
            duration = 60.0
        if duration <= 0:
            duration = 60.0

        seg_duration = duration / len(sentences)
        segments = []
        for i, sentence in enumerate(sentences):
            start = i * seg_duration
            end = start + seg_duration
            raw_words = sentence.split() if lang == "en" else _cjk_words(sentence)
            n_words = len(raw_words)
            words = []
            w_start = start
            for text in raw_words:
                w_end = min(end, w_start + seg_duration / n_words)
                if w_end <= w_start:
                    w_end = w_start + 0.01
                words.append(Word(text=text, start=w_start, end=w_end))
                w_start = w_end
            segments.append(Segment(id=i, start=start, end=end, text=sentence, words=words))

        return TranscriptionResult(
            segments=segments,
            language=lang,
            media_duration=duration,
            model_size=self.model_size,
        )


def get_backend(name: str | None = None) -> ASRBackend:
    """Resolve an ASR backend by name (arg > SFC_ASR_BACKEND env > whisperx).

    Raises ASRError for unknown backend names.
    """
    resolved = name or os.environ.get("SFC_ASR_BACKEND") or "whisperx"
    if resolved == "whisperx":
        return WhisperXBackend()
    if resolved == "faster-whisper":
        return FasterWhisperBackend()
    if resolved == "mock":
        return MockBackend()
    raise ASRError(f"unknown ASR backend {resolved!r}; valid options: {VALID_BACKENDS}")
