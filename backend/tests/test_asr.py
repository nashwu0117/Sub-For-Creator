"""Tests for the ASR backend abstraction."""

import pytest

from app.core.asr import (
    TIER_PRESETS,
    VALID_TIERS,
    ASRBackend,
    ASRConfig,
    FasterWhisperBackend,
    MockBackend,
    WhisperXBackend,
    get_backend,
    resolve_asr_config,
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
    # default tier is "standard" -> medium model, beam 5, temperature 0, VAD on
    assert WhisperXBackend().model_size == "medium"
    assert FasterWhisperBackend().model_size == "medium"
    assert MockBackend().model_size == "mock"
    assert WhisperXBackend().beam_size == 5
    assert WhisperXBackend().temperature == 0.0
    assert WhisperXBackend().vad_enabled is True


def test_whisperx_model_size_from_env(monkeypatch):
    monkeypatch.setenv("SFC_WHISPERX_MODEL", "tiny")
    assert WhisperXBackend().model_size == "tiny"
    assert WhisperXBackend("small").model_size == "small"


def test_faster_whisper_model_size_from_env(monkeypatch):
    monkeypatch.setenv("SFC_WHISPER_MODEL", "base")
    assert FasterWhisperBackend().model_size == "base"
    assert FasterWhisperBackend("small").model_size == "small"


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


# --- tier presets + resolve_asr_config (accuracy enhancements) -------------


def test_tier_presets_accuracy_enhancements():
    assert TIER_PRESETS["lite"]["denoise_enabled"] is False
    assert TIER_PRESETS["lite"]["loudnorm_enabled"] is False
    assert TIER_PRESETS["lite"]["llm_correction_enabled"] is False
    assert TIER_PRESETS["standard"]["denoise_enabled"] is True
    assert TIER_PRESETS["standard"]["loudnorm_enabled"] is True
    assert TIER_PRESETS["standard"]["llm_correction_enabled"] is False
    assert TIER_PRESETS["pro"]["denoise_enabled"] is True
    assert TIER_PRESETS["pro"]["loudnorm_enabled"] is True
    assert TIER_PRESETS["pro"]["llm_correction_enabled"] is True


def test_valid_tiers_tuple():
    assert VALID_TIERS == ("lite", "standard", "pro")


def test_resolve_accuracy_flags_follow_tier():
    lite = resolve_asr_config(tier="lite")
    assert lite.denoise_enabled is False
    assert lite.loudnorm_enabled is False
    assert lite.llm_correction_enabled is False

    standard = resolve_asr_config(tier="standard")
    assert standard.denoise_enabled is True
    assert standard.loudnorm_enabled is True
    assert standard.llm_correction_enabled is False

    pro = resolve_asr_config(tier="pro")
    assert pro.denoise_enabled is True
    assert pro.loudnorm_enabled is True
    assert pro.llm_correction_enabled is True


def test_resolve_accuracy_explicit_args_win_over_tier():
    cfg = resolve_asr_config(
        tier="pro",
        denoise_enabled=False,
        loudnorm_enabled=False,
        llm_correction_enabled=False,
    )
    assert cfg.denoise_enabled is False
    assert cfg.loudnorm_enabled is False
    assert cfg.llm_correction_enabled is False


def test_resolve_accuracy_env_wins_over_tier(monkeypatch):
    monkeypatch.setenv("SFC_DENOISE_ENABLED", "false")
    monkeypatch.setenv("SFC_LOUDNORM_ENABLED", "false")
    monkeypatch.setenv("SFC_LLM_CORRECTION_ENABLED", "true")
    cfg = resolve_asr_config(tier="pro")
    assert cfg.denoise_enabled is False
    assert cfg.loudnorm_enabled is False
    assert cfg.llm_correction_enabled is True


def test_resolve_accuracy_env_true_variants(monkeypatch):
    for raw in ("1", "true", "yes", "on"):
        monkeypatch.setenv("SFC_DENOISE_ENABLED", raw)
        assert resolve_asr_config(tier="lite").denoise_enabled is True


def test_resolve_model_env_falls_back_to_tier(monkeypatch):
    monkeypatch.delenv("SFC_WHISPERX_MODEL", raising=False)
    cfg = resolve_asr_config(tier="lite", model_env="SFC_WHISPERX_MODEL")
    assert cfg.model_size == "small"

    monkeypatch.setenv("SFC_WHISPERX_MODEL", "tiny")
    cfg = resolve_asr_config(tier="pro", model_env="SFC_WHISPERX_MODEL")
    assert cfg.model_size == "tiny"


def test_resolve_returns_asr_config_with_accuracy_fields():
    cfg = resolve_asr_config(tier="pro")
    assert isinstance(cfg, ASRConfig)
    assert cfg.tier == "pro"
    assert cfg.denoise_enabled is True
    assert cfg.loudnorm_enabled is True
    assert cfg.llm_correction_enabled is True
