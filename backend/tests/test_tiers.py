"""Tests for the ASR accuracy tier system.

Covers tier preset resolution, override precedence (arg > env > tier),
VAD flag plumbing for both real backends, temperature=0 determinism at the
mock level, and CLI flag parsing. No real models are loaded: whisperx is
faked via ``sys.modules`` injection and faster-whisper via a fake model class.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from app.core.asr import (
    TIER_PRESETS,
    VALID_TIERS,
    ASRConfig,
    FasterWhisperBackend,
    MockBackend,
    WhisperXBackend,
    get_backend,
    resolve_asr_config,
)
from app.core.exceptions import ASRError

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def make_file(tmp_path, name="audio.wav") -> str:
    path = tmp_path / name
    path.write_bytes(b"")
    return str(path)


# --- tier preset resolution -------------------------------------------------


def test_tier_presets_match_spec():
    assert TIER_PRESETS["lite"]["model_size"] == "small"
    assert TIER_PRESETS["lite"]["compute_type"] == "int8"
    assert TIER_PRESETS["lite"]["beam_size"] == 5
    assert TIER_PRESETS["standard"]["model_size"] == "medium"
    assert TIER_PRESETS["standard"]["beam_size"] == 5
    assert TIER_PRESETS["pro"]["model_size"] == "large-v3"
    assert TIER_PRESETS["pro"]["beam_size"] == 10
    for preset in TIER_PRESETS.values():
        assert preset["temperature"] == 0.0
        assert preset["vad_enabled"] is True


def test_valid_tiers():
    assert VALID_TIERS == ("lite", "standard", "pro")


def test_resolve_default_tier_is_standard():
    cfg = resolve_asr_config()
    assert cfg.tier == "standard"
    assert cfg.model_size == "medium"
    assert cfg.beam_size == 5
    assert cfg.temperature == 0.0
    assert cfg.vad_enabled is True
    assert cfg.compute_type is None  # device-based default


def test_resolve_tier_presets():
    lite = resolve_asr_config(tier="lite")
    assert lite.model_size == "small"
    assert lite.compute_type == "int8"
    assert lite.beam_size == 5
    pro = resolve_asr_config(tier="pro")
    assert pro.model_size == "large-v3"
    assert pro.beam_size == 10


def test_resolve_unknown_tier_raises():
    with pytest.raises(ASRError):
        resolve_asr_config(tier="ultra")


def test_resolve_explicit_args_win_over_tier():
    cfg = resolve_asr_config(
        tier="lite",
        model_size="large-v3",
        beam_size=10,
        temperature=0.5,
        vad_enabled=False,
    )
    assert cfg.model_size == "large-v3"
    assert cfg.beam_size == 10
    assert cfg.temperature == 0.5
    assert cfg.vad_enabled is False


def test_resolve_env_wins_over_tier(monkeypatch):
    monkeypatch.setenv("SFC_TIER", "pro")
    monkeypatch.setenv("SFC_BEAM_SIZE", "7")
    monkeypatch.setenv("SFC_TEMPERATURE", "0.2")
    monkeypatch.setenv("SFC_VAD_ENABLED", "false")
    cfg = resolve_asr_config()
    assert cfg.tier == "pro"
    assert cfg.beam_size == 7
    assert cfg.temperature == 0.2
    assert cfg.vad_enabled is False


def test_resolve_model_env_wins_over_tier(monkeypatch):
    monkeypatch.setenv("SFC_TIER", "lite")
    monkeypatch.setenv("SFC_WHISPERX_MODEL", "tiny")
    assert resolve_asr_config(model_env="SFC_WHISPERX_MODEL").model_size == "tiny"
    monkeypatch.setenv("SFC_WHISPER_MODEL", "base")
    assert resolve_asr_config(model_env="SFC_WHISPER_MODEL").model_size == "base"


def test_resolve_invalid_env_values_ignored(monkeypatch):
    monkeypatch.setenv("SFC_BEAM_SIZE", "not-a-number")
    monkeypatch.setenv("SFC_TEMPERATURE", "hot")
    cfg = resolve_asr_config(tier="pro")
    assert cfg.beam_size == 10
    assert cfg.temperature == 0.0


def test_resolve_returns_asr_config():
    assert isinstance(resolve_asr_config(), ASRConfig)


# --- backend construction ---------------------------------------------------


def test_backend_defaults_follow_tier():
    assert WhisperXBackend().model_size == "medium"
    assert WhisperXBackend().beam_size == 5
    assert WhisperXBackend().temperature == 0.0
    assert WhisperXBackend().vad_enabled is True
    assert FasterWhisperBackend().model_size == "medium"
    assert WhisperXBackend(tier="pro").model_size == "large-v3"
    assert WhisperXBackend(tier="pro").beam_size == 10
    assert FasterWhisperBackend(tier="lite").model_size == "small"


def test_backend_explicit_model_wins_over_tier():
    assert WhisperXBackend("tiny", tier="pro").model_size == "tiny"
    assert FasterWhisperBackend("base", tier="pro").model_size == "base"


def test_get_backend_forwards_tier():
    backend = get_backend("whisperx", tier="pro")
    assert isinstance(backend, WhisperXBackend)
    assert backend.model_size == "large-v3"
    assert backend.beam_size == 10
    fast = get_backend("faster-whisper", tier="lite", vad_enabled=False)
    assert isinstance(fast, FasterWhisperBackend)
    assert fast.model_size == "small"
    assert fast.vad_enabled is False


def test_get_backend_unknown_tier_raises():
    with pytest.raises(ASRError):
        get_backend("whisperx", tier="ultra")


# --- whisperx VAD + decode plumbing (faked whisperx) ------------------------


class _FakeWhisperXModel:
    def __init__(self, captured):
        self.captured = captured

    def transcribe(self, audio, language=None):
        self.captured["transcribe_language"] = language
        return {
            "language": language or "zh",
            "segments": [
                {
                    "start": 0.0,
                    "end": 2.0,
                    "text": " 你好 ",
                    "words": [{"word": "你好", "start": 0.0, "end": 2.0}],
                }
            ],
        }


class _FakeWhisperX:
    def __init__(self, captured):
        self.captured = captured
        self.calls = 0

    def load_model(
        self,
        whisper_arch,
        device,
        compute_type="float16",
        asr_options=None,
        vad_model=None,
        vad_method="pyannote",
        vad_options=None,
        **kwargs,
    ):
        self.calls += 1
        self.captured["load_kwargs_list"].append(
            {
                "whisper_arch": whisper_arch,
                "device": device,
                "compute_type": compute_type,
                "asr_options": asr_options,
                "vad_model": vad_model,
                "vad_method": vad_method,
                "vad_options": vad_options,
            }
        )
        if self.calls <= self.captured["fail_first"]:
            raise RuntimeError("simulated VAD load failure")
        return _FakeWhisperXModel(self.captured)

    def load_audio(self, path):
        return np.zeros(16000 * 10, dtype=np.float32)

    def load_align_model(self, language_code=None, device=None):
        return None, None

    def align(self, segments, align_model, metadata, audio, device):
        return {"segments": segments}


class _FakeVad:
    def __init__(self, vad_onset):
        if not (0 < vad_onset < 1):
            raise ValueError("vad_onset must be between 0 and 1")

    @staticmethod
    def preprocess_audio(audio):
        return audio

    @staticmethod
    def merge_chunks(segments, chunk_size, onset, offset):
        return [
            {"start": seg.start, "end": seg.end, "segments": [(seg.start, seg.end)]}
            for seg in segments
        ]


@pytest.fixture
def fake_whisperx(monkeypatch):
    captured = {"load_kwargs_list": [], "fail_first": 0}
    fake = _FakeWhisperX(captured)

    wx = types.ModuleType("whisperx")
    wx.load_model = fake.load_model
    wx.load_audio = fake.load_audio
    wx.load_align_model = fake.load_align_model
    wx.align = fake.align

    vads = types.ModuleType("whisperx.vads")
    vad_mod = types.ModuleType("whisperx.vads.vad")
    vad_mod.Vad = _FakeVad
    vads.vad = vad_mod
    wx.vads = vads

    monkeypatch.setitem(sys.modules, "whisperx", wx)
    monkeypatch.setitem(sys.modules, "whisperx.vads", vads)
    monkeypatch.setitem(sys.modules, "whisperx.vads.vad", vad_mod)
    return captured


def test_whisperx_vad_enabled_passes_pyannote(fake_whisperx, tmp_path):
    path = make_file(tmp_path)
    result = WhisperXBackend(tier="standard").transcribe(path, "zh")
    kwargs = fake_whisperx["load_kwargs_list"][0]
    assert kwargs["vad_method"] == "pyannote"
    assert kwargs["vad_options"] == {"vad_onset": 0.5, "vad_offset": 0.363}
    assert kwargs["asr_options"]["beam_size"] == 5
    assert kwargs["asr_options"]["temperatures"] == [0.0]
    assert fake_whisperx["transcribe_language"] == "zh"
    assert result.language == "zh"
    assert result.segments[0].text == "你好"


def test_whisperx_vad_disabled_injects_noop_vad(fake_whisperx, tmp_path):
    path = make_file(tmp_path)
    WhisperXBackend(vad_enabled=False).transcribe(path, "zh")
    kwargs = fake_whisperx["load_kwargs_list"][0]
    # a manually-assigned vad_model takes priority over vad_method in whisperx
    assert kwargs["vad_model"] is not None
    # the no-op VAD reports the whole audio as one speech segment
    vad = kwargs["vad_model"]
    segs = vad({"waveform": np.zeros(16000 * 5), "sample_rate": 16000})
    assert len(segs) == 1
    assert segs[0].start == 0.0
    assert segs[0].end == pytest.approx(5.0)


def test_whisperx_vad_falls_back_to_silero(fake_whisperx, tmp_path):
    fake_whisperx["fail_first"] = 1
    path = make_file(tmp_path)
    WhisperXBackend().transcribe(path, "zh")
    calls = fake_whisperx["load_kwargs_list"]
    assert len(calls) == 2
    assert calls[0]["vad_method"] == "pyannote"
    assert calls[1]["vad_method"] == "silero"


def test_whisperx_vad_falls_back_to_noop(fake_whisperx, tmp_path):
    fake_whisperx["fail_first"] = 2
    path = make_file(tmp_path)
    WhisperXBackend().transcribe(path, "zh")
    calls = fake_whisperx["load_kwargs_list"]
    assert len(calls) == 3
    assert calls[0]["vad_method"] == "pyannote"
    assert calls[1]["vad_method"] == "silero"
    assert calls[2]["vad_model"] is not None


def test_whisperx_pro_beam_size(fake_whisperx, tmp_path):
    path = make_file(tmp_path)
    WhisperXBackend(tier="pro").transcribe(path, "zh")
    kwargs = fake_whisperx["load_kwargs_list"][0]
    assert kwargs["asr_options"]["beam_size"] == 10


# --- faster-whisper decode + VAD plumbing (faked model) ---------------------


class _FakeWord:
    def __init__(self, word, start, end):
        self.word = word
        self.start = start
        self.end = end


class _FakeSegment:
    def __init__(self, start, end, text, words):
        self.start = start
        self.end = end
        self.text = text
        self.words = words


class _FakeInfo:
    language = "zh"
    duration = 10.0


def _install_fake_faster_whisper(monkeypatch, captured):
    class FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            captured["model_kwargs"] = kwargs

        def transcribe(self, audio_path, **kwargs):
            captured["transcribe_kwargs"] = kwargs
            seg = _FakeSegment(0.0, 2.0, "你好", [_FakeWord("你好", 0.0, 2.0)])
            return iter([seg]), _FakeInfo()

    monkeypatch.setattr("faster_whisper.WhisperModel", FakeWhisperModel)


def test_faster_whisper_passes_decode_and_vad_params(monkeypatch, tmp_path):
    captured = {}
    _install_fake_faster_whisper(monkeypatch, captured)
    path = make_file(tmp_path)
    result = FasterWhisperBackend(tier="pro").transcribe(path, "zh")
    tk = captured["transcribe_kwargs"]
    assert tk["beam_size"] == 10
    assert tk["temperature"] == 0.0
    assert tk["vad_filter"] is True
    assert tk["vad_parameters"] == {"threshold": 0.5}
    assert tk["language"] == "zh"
    assert result.language == "zh"
    assert result.segments[0].text == "你好"


def test_faster_whisper_vad_disabled(monkeypatch, tmp_path):
    captured = {}
    _install_fake_faster_whisper(monkeypatch, captured)
    path = make_file(tmp_path)
    FasterWhisperBackend(vad_enabled=False).transcribe(path, "zh")
    tk = captured["transcribe_kwargs"]
    assert tk["vad_filter"] is False
    assert tk["vad_parameters"] is None


def test_faster_whisper_temperature_zero_deterministic(monkeypatch, tmp_path):
    captured = {}
    _install_fake_faster_whisper(monkeypatch, captured)
    path = make_file(tmp_path)
    backend = FasterWhisperBackend(tier="pro")
    a = backend.transcribe(path, "zh")
    b = backend.transcribe(path, "zh")
    assert a == b
    assert captured["transcribe_kwargs"]["temperature"] == 0.0


def test_mock_temperature_zero_deterministic(tmp_path):
    path = make_file(tmp_path)
    a = MockBackend().transcribe(path, "zh")
    b = MockBackend().transcribe(path, "zh")
    assert a == b


# --- CLI flag parsing -------------------------------------------------------


def test_cli_parser_accepts_tier_flags():
    from cli.subforcreator import build_parser

    args = build_parser().parse_args(
        [
            "video.mp4",
            "--tier",
            "pro",
            "--beam-size",
            "10",
            "--temperature",
            "0",
            "--no-vad",
            "--lang",
            "zh",
        ]
    )
    assert args.tier == "pro"
    assert args.beam_size == 10
    assert args.temperature == 0.0
    assert args.no_vad is True
    assert args.lang == "zh"


def test_cli_parser_defaults():
    from cli.subforcreator import build_parser

    args = build_parser().parse_args(["video.mp4"])
    assert args.tier is None
    assert args.model is None
    assert args.beam_size is None
    assert args.temperature is None
    assert args.no_vad is False
    assert args.lang is None


def test_cli_parser_rejects_unknown_tier():
    from cli.subforcreator import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["video.mp4", "--tier", "ultra"])


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_cli_tier_flags_end_to_end(tmp_path):
    wav = tmp_path / "in.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(wav)],
        check=True,
        capture_output=True,
    )
    out = tmp_path / "out.srt"
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "cli" / "subforcreator.py"),
            str(wav),
            "--mock",
            "--tier",
            "pro",
            "--beam-size",
            "10",
            "--temperature",
            "0",
            "--no-vad",
            "--lang",
            "zh",
            "-o",
            str(out),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    assert out.exists()
    assert "-->" in out.read_text(encoding="utf-8")


# --- VAD hallucination fixture (mock-level) ---------------------------------


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_vad_fixture_sine_plus_silence(tmp_path):
    """Generate the 10s sine + 5s silence fixture used for VAD acceptance.

    Mock-level check: the fixture is well-formed (probes to ~15s) and the
    whisperx backend is wired to run pyannote VAD over it, which is what
    filters the silent middle section in real-model runs.
    """
    from app.core.audio import probe_duration

    wav = tmp_path / "sine_silence.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=10",
            "-af",
            "apad=pad_dur=5",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(wav),
        ],
        check=True,
        capture_output=True,
    )
    assert 14.5 <= probe_duration(str(wav)) <= 15.5
