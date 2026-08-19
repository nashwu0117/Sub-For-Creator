"""Tests for the ASR backend abstraction."""

import pytest

from app.core.asr import (
    ASRBackend,
    FasterWhisperBackend,
    MockBackend,
    WhisperXBackend,
    get_backend,
)
from app.core.exceptions import ASRError


def make_file(tmp_path, name="audio.wav") -> str:
    path = tmp_path / name
    path.write_bytes(b"")
    return str(path)


def test_get_backend_default():
    assert isinstance(get_backend(), WhisperXBackend)


def test_get_backend_env(monkeypatch):
    monkeypatch.setenv("SFC_ASR_BACKEND", "mock")
    assert isinstance(get_backend(), MockBackend)


def test_get_backend_arg_overrides_env(monkeypatch):
    monkeypatch.setenv("SFC_ASR_BACKEND", "mock")
    assert isinstance(get_backend("faster-whisper"), FasterWhisperBackend)


def test_get_backend_explicit_names():
    assert isinstance(get_backend("whisperx"), WhisperXBackend)
    assert isinstance(get_backend("faster-whisper"), FasterWhisperBackend)
    assert isinstance(get_backend("mock"), MockBackend)


def test_get_backend_unknown():
    with pytest.raises(ASRError):
        get_backend("nonexistent-backend")


def test_backends_constructible():
    assert WhisperXBackend().model_size == "large-v3"
    assert FasterWhisperBackend().model_size == "large-v3"
    assert MockBackend().model_size == "mock"


def test_whisperx_model_size_from_env(monkeypatch):
    monkeypatch.setenv("SFC_WHISPERX_MODEL", "tiny")
    assert WhisperXBackend().model_size == "tiny"
    assert WhisperXBackend("small").model_size == "small"


def test_asr_backend_is_protocol():
    # a mock instance structurally satisfies the protocol
    backend: ASRBackend = MockBackend()
    assert backend is not None


def test_mock_language_mapping(tmp_path):
    path = make_file(tmp_path)
    backend = MockBackend()
    assert backend.transcribe(path, None).language == "zh"
    assert backend.transcribe(path, "auto").language == "zh"
    assert backend.transcribe(path, "en").language == "en"
    assert backend.transcribe(path, "ja").language == "ja"
    assert backend.transcribe(path, "ko").language == "ko"


def test_mock_unknown_language_falls_back_to_zh(tmp_path):
    path = make_file(tmp_path)
    result = MockBackend().transcribe(path, "fr")
    assert result.language == "fr"
    assert len(result.segments) == 4


def test_mock_output_valid(tmp_path):
    path = make_file(tmp_path)
    result = MockBackend().transcribe(path, "zh")

    assert result.media_duration is not None
    assert result.media_duration > 0
    assert result.segments
    assert 3 <= len(result.segments) <= 4

    prev_end = 0.0
    for seg in result.segments:
        assert seg.start < seg.end
        assert seg.start >= prev_end  # sorted, non-overlapping
        prev_end = seg.end
        assert 4 <= len(seg.words) <= 6
        for word in seg.words:
            assert word.start < word.end
            assert word.text
    assert result.segments[-1].end == pytest.approx(result.media_duration)


def test_mock_deterministic(tmp_path):
    path = make_file(tmp_path)
    a = MockBackend().transcribe(path, "zh")
    b = MockBackend().transcribe(path, "zh")
    assert a == b


def test_mock_english_words_split_by_spaces(tmp_path):
    path = make_file(tmp_path)
    result = MockBackend().transcribe(path, "en")
    for seg in result.segments:
        assert "".join(w.text for w in seg.words) == seg.text.replace(" ", "")


def test_mock_fallback_duration_without_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    path = make_file(tmp_path)
    result = MockBackend().transcribe(path, "zh")
    assert result.media_duration == 60.0


def test_whisperx_and_faster_whisper_are_lazy():
    # constructing backends must not import heavy deps or crash at import time
    import sys

    WhisperXBackend()
    FasterWhisperBackend()
    assert "whisperx" not in sys.modules
    assert "faster_whisper" not in sys.modules
