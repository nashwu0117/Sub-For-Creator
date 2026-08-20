"""ASR backend abstraction.

Backends implement the ASRBackend protocol and return a TranscriptionResult.
Heavy ML frameworks (whisperx, faster-whisper) are imported lazily inside
``transcribe`` so the rest of the app and the test suite never need them
installed; the mock backend needs neither a model nor ffmpeg.

Accuracy tiers (``SFC_TIER``) layer on top of the flat backend selection:
each tier pins a default model size, beam size, temperature and VAD policy.
Explicit model env vars (``SFC_WHISPERX_MODEL`` / ``SFC_WHISPER_MODEL``) and
constructor arguments always win over the tier default.
"""

from __future__ import annotations

import inspect
import logging
import os
from dataclasses import dataclass
from typing import Protocol

from .audio import probe_duration
from .exceptions import ASRError, MediaProcessingError
from .models import Segment, TranscriptionResult, Word

logger = logging.getLogger(__name__)

VALID_BACKENDS = ("whisperx", "faster-whisper", "mock")

VALID_TIERS = ("lite", "standard", "pro")

#: Tier presets — model size / beam size / temperature / VAD per tier.
#: ``compute_type`` is optional; when absent the backend picks a device-based
#: default (float16 on CUDA, int8 on CPU).
TIER_PRESETS: dict[str, dict[str, object]] = {
    "lite": {
        "model_size": "small",
        "compute_type": "int8",
        "beam_size": 5,
        "temperature": 0.0,
        "vad_enabled": True,
    },
    "standard": {
        "model_size": "medium",
        "beam_size": 5,
        "temperature": 0.0,
        "vad_enabled": True,
    },
    "pro": {
        "model_size": "large-v3",
        "beam_size": 10,
        "temperature": 0.0,
        "vad_enabled": True,
    },
}

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


# --- tier resolution --------------------------------------------------------


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("invalid integer for %s=%r; ignoring", name, raw)
        return None


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        logger.warning("invalid float for %s=%r; ignoring", name, raw)
        return None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class ASRConfig:
    """Resolved ASR parameters (tier preset + explicit overrides applied)."""

    tier: str = "standard"
    model_size: str = "medium"
    compute_type: str | None = None
    beam_size: int = 5
    temperature: float = 0.0
    vad_enabled: bool = True
    vad_onset: float = 0.5
    vad_offset: float = 0.363


def resolve_asr_config(
    *,
    tier: str | None = None,
    model_size: str | None = None,
    model_env: str | None = None,
    beam_size: int | None = None,
    temperature: float | None = None,
    vad_enabled: bool | None = None,
) -> ASRConfig:
    """Resolve effective ASR parameters.

    Precedence per parameter: explicit argument > ``SFC_*`` env var > tier
    preset > built-in default. ``model_env`` selects the backend-specific
    model env var (``SFC_WHISPERX_MODEL`` or ``SFC_WHISPER_MODEL``).
    """
    tier = tier or os.environ.get("SFC_TIER") or "standard"
    if tier not in TIER_PRESETS:
        raise ASRError(f"unknown tier {tier!r}; valid options: {VALID_TIERS}")
    preset = TIER_PRESETS[tier]

    if model_size is None and model_env:
        model_size = os.environ.get(model_env)
    if model_size is None:
        model_size = str(preset["model_size"])

    if beam_size is None:
        beam_size = _env_int("SFC_BEAM_SIZE")
    if beam_size is None:
        beam_size = int(preset["beam_size"])

    if temperature is None:
        temperature = _env_float("SFC_TEMPERATURE")
    if temperature is None:
        temperature = float(preset["temperature"])

    if vad_enabled is None:
        vad_enabled = _env_bool("SFC_VAD_ENABLED", bool(preset["vad_enabled"]))

    compute_type = preset.get("compute_type")
    return ASRConfig(
        tier=tier,
        model_size=model_size,
        compute_type=str(compute_type) if compute_type is not None else None,
        beam_size=beam_size,
        temperature=temperature,
        vad_enabled=vad_enabled,
    )


class _VADSegment:
    """Minimal speech-segment record consumed by whisperx VAD merge logic."""

    __slots__ = ("start", "end", "speaker")

    def __init__(self, start: float, end: float, speaker: str = "UNKNOWN"):
        self.start = start
        self.end = end
        self.speaker = speaker


def _supports_vad_method(whisperx) -> bool:
    """True when whisperx.load_model exposes ``vad_method`` (whisperx >= 3.4)."""
    try:
        return "vad_method" in inspect.signature(whisperx.load_model).parameters
    except (TypeError, ValueError):
        return False


class WhisperXBackend:
    """WhisperX transcription backend (lazy import; GPU-accelerated when available).

    VAD: whisperx >= 3.4 applies VAD at model-load time via ``vad_method``
    (pyannote by default, silero as fallback). When VAD is disabled or every
    VAD backend is unavailable, a no-op VAD is injected so the whole audio is
    still transcribed. Decode options (beam size / temperature) are passed via
    ``asr_options``.
    """

    def __init__(
        self,
        model_size: str | None = None,
        *,
        tier: str | None = None,
        beam_size: int | None = None,
        temperature: float | None = None,
        vad_enabled: bool | None = None,
        vad_onset: float | None = None,
        vad_offset: float | None = None,
    ):
        cfg = resolve_asr_config(
            tier=tier,
            model_size=model_size,
            model_env="SFC_WHISPERX_MODEL",
            beam_size=beam_size,
            temperature=temperature,
            vad_enabled=vad_enabled,
        )
        self.model_size = cfg.model_size
        self.compute_type = cfg.compute_type
        self.beam_size = cfg.beam_size
        self.temperature = cfg.temperature
        self.vad_enabled = cfg.vad_enabled
        self.vad_onset = vad_onset if vad_onset is not None else cfg.vad_onset
        self.vad_offset = vad_offset if vad_offset is not None else cfg.vad_offset

    def transcribe(self, audio_path: str, language: str | None = None) -> TranscriptionResult:
        try:
            import whisperx
        except ImportError as exc:
            raise ASRError(
                "whisperx is not installed; install backend/requirements-gpu.txt "
                "to use the whisperx backend"
            ) from exc

        device = "cuda" if _cuda_available() else "cpu"
        compute_type = self.compute_type or ("float16" if device == "cuda" else "int8")
        model = self._load_model(whisperx, device, compute_type)
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

    def _load_model(self, whisperx, device: str, compute_type: str):
        """Load a whisperx pipeline with VAD + decode options applied.

        VAD degrades gracefully: pyannote -> silero -> no-op (whole audio).
        """
        asr_options = {
            "beam_size": self.beam_size,
            "temperatures": [self.temperature],
        }
        load_kwargs: dict[str, object] = {
            "whisper_arch": self.model_size,
            "device": device,
            "compute_type": compute_type,
            "asr_options": asr_options,
        }
        if not self.vad_enabled:
            return self._load_without_vad(whisperx, load_kwargs)

        load_kwargs["vad_options"] = {
            "vad_onset": self.vad_onset,
            "vad_offset": self.vad_offset,
        }
        if _supports_vad_method(whisperx):
            load_kwargs["vad_method"] = "pyannote"
        try:
            return whisperx.load_model(**load_kwargs)
        except Exception as exc:  # noqa: BLE001 - VAD is best-effort
            logger.warning("pyannote VAD unavailable (%s); falling back to silero VAD", exc)
            if _supports_vad_method(whisperx):
                load_kwargs["vad_method"] = "silero"
                try:
                    return whisperx.load_model(**load_kwargs)
                except Exception as exc2:  # noqa: BLE001 - VAD is best-effort
                    logger.warning("silero VAD unavailable (%s); continuing WITHOUT VAD", exc2)
            return self._load_without_vad(whisperx, load_kwargs)

    def _load_without_vad(self, whisperx, load_kwargs: dict[str, object]):
        """Load whisperx with a no-op VAD so the full audio is transcribed."""
        from whisperx.vads.vad import Vad

        class _NoOpVAD(Vad):
            """VAD stand-in reporting the whole audio as one speech segment."""

            def __init__(self):
                super().__init__(0.5)

            def __call__(self, audio):
                waveform = audio["waveform"]
                sample_rate = audio["sample_rate"]
                duration = waveform.shape[-1] / sample_rate
                return [_VADSegment(0.0, duration)]

            @staticmethod
            def preprocess_audio(audio):
                return audio

        kwargs = dict(load_kwargs)
        kwargs.pop("vad_method", None)
        kwargs.pop("vad_options", None)
        kwargs["vad_model"] = _NoOpVAD()
        return whisperx.load_model(**kwargs)


class FasterWhisperBackend:
    """faster-whisper transcription backend (lazy import).

    VAD (``vad_filter``) and decode options (``beam_size`` / ``temperature``)
    are native faster-whisper ``transcribe`` parameters.
    """

    def __init__(
        self,
        model_size: str | None = None,
        *,
        tier: str | None = None,
        beam_size: int | None = None,
        temperature: float | None = None,
        vad_enabled: bool | None = None,
        vad_onset: float | None = None,
    ):
        cfg = resolve_asr_config(
            tier=tier,
            model_size=model_size,
            model_env="SFC_WHISPER_MODEL",
            beam_size=beam_size,
            temperature=temperature,
            vad_enabled=vad_enabled,
        )
        self.model_size = cfg.model_size
        self.compute_type = cfg.compute_type
        self.beam_size = cfg.beam_size
        self.temperature = cfg.temperature
        self.vad_enabled = cfg.vad_enabled
        self.vad_onset = vad_onset if vad_onset is not None else cfg.vad_onset

    def transcribe(self, audio_path: str, language: str | None = None) -> TranscriptionResult:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ASRError(
                "faster-whisper is not installed; install backend/requirements.txt "
                "to use the faster-whisper backend"
            ) from exc

        device = "cuda" if _cuda_available() else "cpu"
        compute_type = self.compute_type or ("float16" if device == "cuda" else "int8")
        model = WhisperModel(self.model_size, device=device, compute_type=compute_type)
        vad_parameters = {"threshold": self.vad_onset} if self.vad_enabled else None
        segments_iter, info = model.transcribe(
            audio_path,
            language=_resolve_language(language),
            word_timestamps=True,
            vad_filter=self.vad_enabled,
            vad_parameters=vad_parameters,
            beam_size=self.beam_size,
            temperature=self.temperature,
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


def get_backend(
    name: str | None = None,
    *,
    tier: str | None = None,
    model_size: str | None = None,
    beam_size: int | None = None,
    temperature: float | None = None,
    vad_enabled: bool | None = None,
) -> ASRBackend:
    """Resolve an ASR backend by name (arg > SFC_ASR_BACKEND env > whisperx).

    ``tier`` / ``model_size`` / ``beam_size`` / ``temperature`` / ``vad_enabled``
    are forwarded to the backend constructor; each falls back to the matching
    ``SFC_*`` env var and then to the tier preset. Raises ASRError for unknown
    backend names or tiers.
    """
    resolved = name or os.environ.get("SFC_ASR_BACKEND") or "whisperx"
    if resolved == "whisperx":
        return WhisperXBackend(
            model_size=model_size,
            tier=tier,
            beam_size=beam_size,
            temperature=temperature,
            vad_enabled=vad_enabled,
        )
    if resolved == "faster-whisper":
        return FasterWhisperBackend(
            model_size=model_size,
            tier=tier,
            beam_size=beam_size,
            temperature=temperature,
            vad_enabled=vad_enabled,
        )
    if resolved == "mock":
        return MockBackend()
    raise ASRError(f"unknown ASR backend {resolved!r}; valid options: {VALID_BACKENDS}")
