"""Tests for audio preprocessing: denoising and loudness normalization.

Heavy deps (noisereduce, scipy) and ffmpeg are faked via ``sys.modules``
injection and monkeypatched helpers — no real audio processing or network is
involved.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from app.core.exceptions import AudioExtractionError
from app.core.preprocess import denoise_audio, normalize_loudness, preprocess_audio


def make_file(tmp_path, name="audio.wav") -> str:
    path = tmp_path / name
    path.write_bytes(b"")
    return str(path)


# --- denoise_audio ---------------------------------------------------------


def _install_fake_denoise_deps(monkeypatch, captured, read_error=None):
    """Inject fake noisereduce + scipy.io.wavfile into sys.modules."""
    nr = types.ModuleType("noisereduce")

    def reduce_noise(**kwargs):
        captured["reduce_kwargs"] = kwargs
        return kwargs["y"] * 0.5

    nr.reduce_noise = reduce_noise

    wavfile = types.ModuleType("scipy.io.wavfile")

    def _read(path):
        if read_error is not None:
            raise read_error
        return 16000, np.zeros(16000, dtype=np.int16)

    wavfile.read = _read
    wavfile.write = lambda path, sr, data: captured.setdefault("write", (path, sr, data))

    scipy_io = types.ModuleType("scipy.io")
    scipy_io.wavfile = wavfile
    scipy = types.ModuleType("scipy")
    scipy.io = scipy_io

    monkeypatch.setitem(sys.modules, "noisereduce", nr)
    monkeypatch.setitem(sys.modules, "scipy", scipy)
    monkeypatch.setitem(sys.modules, "scipy.io", scipy_io)
    monkeypatch.setitem(sys.modules, "scipy.io.wavfile", wavfile)


def test_denoise_audio_reads_int16_and_writes_int16(monkeypatch, tmp_path):
    captured: dict = {}
    _install_fake_denoise_deps(monkeypatch, captured)
    input_path = make_file(tmp_path, "in.wav")
    output_path = str(tmp_path / "out.wav")

    denoise_audio(input_path, output_path)

    kwargs = captured["reduce_kwargs"]
    assert kwargs["sr"] == 16000
    assert kwargs["prop_decrease"] == 0.75
    assert kwargs["stationary"] is True
    assert kwargs["n_std_thresh_stationary"] == 1.5
    assert kwargs["y"].dtype == np.float32  # int16 input scaled to float32
    write_path, write_sr, write_data = captured["write"]
    assert write_path == output_path
    assert write_sr == 16000
    assert write_data.dtype == np.int16


def test_denoise_audio_accepts_float32_input(monkeypatch, tmp_path):
    captured: dict = {}
    _install_fake_denoise_deps(monkeypatch, captured)
    # float32 input must NOT be scaled by 32768
    captured["reduce_kwargs"] = None
    wavfile = sys.modules["scipy.io.wavfile"]
    wavfile.read = lambda path: (16000, np.ones(16000, dtype=np.float32))

    denoise_audio(make_file(tmp_path), str(tmp_path / "out.wav"))

    assert captured["reduce_kwargs"]["y"].dtype == np.float32
    assert captured["reduce_kwargs"]["y"].max() == pytest.approx(1.0)


def test_denoise_audio_missing_deps_raises(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "noisereduce", None)
    with pytest.raises(AudioExtractionError, match="noisereduce/scipy not installed"):
        denoise_audio(make_file(tmp_path), str(tmp_path / "out.wav"))


def test_denoise_audio_wraps_failures(monkeypatch, tmp_path):
    captured: dict = {}
    _install_fake_denoise_deps(monkeypatch, captured, read_error=ValueError("corrupt wav"))
    with pytest.raises(AudioExtractionError, match="denoising failed"):
        denoise_audio(make_file(tmp_path), str(tmp_path / "out.wav"))


# --- normalize_loudness ----------------------------------------------------


def test_normalize_loudness_builds_ffmpeg_command(monkeypatch, tmp_path):
    captured: dict = {}
    monkeypatch.setattr("app.core.preprocess._require", lambda binary: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        "app.core.preprocess._run",
        lambda cmd, context: captured.setdefault("cmd", cmd),
    )
    input_path = make_file(tmp_path, "in.wav")
    output_path = str(tmp_path / "out.wav")

    normalize_loudness(input_path, output_path)

    cmd = captured["cmd"]
    assert cmd[0] == "/usr/bin/ffmpeg"
    assert "-y" in cmd
    assert "-i" in cmd
    assert input_path in cmd
    assert "loudnorm=I=-16:TP=-1.5:LRA=11" in cmd
    assert "-ar" in cmd and "16000" in cmd
    assert "-ac" in cmd and "1" in cmd
    assert "-c:a" in cmd and "pcm_s16le" in cmd
    assert cmd[-1] == output_path


def test_normalize_loudness_missing_ffmpeg_raises(monkeypatch, tmp_path):
    def _require(binary):
        raise AudioExtractionError(
            f"{binary} not found; install ffmpeg to process media files"
        )

    monkeypatch.setattr("app.core.preprocess._require", _require)
    with pytest.raises(AudioExtractionError, match="ffmpeg not found"):
        normalize_loudness(make_file(tmp_path), str(tmp_path / "out.wav"))


def test_normalize_loudness_nonzero_exit_raises(monkeypatch, tmp_path):
    monkeypatch.setattr("app.core.preprocess._require", lambda binary: "/usr/bin/ffmpeg")

    def _run(cmd, context):
        raise AudioExtractionError(f"{context}: boom")

    monkeypatch.setattr("app.core.preprocess._run", _run)
    with pytest.raises(AudioExtractionError, match="loudness normalization failed"):
        normalize_loudness(make_file(tmp_path), str(tmp_path / "out.wav"))


# --- preprocess_audio ------------------------------------------------------


def test_preprocess_noop_returns_input(monkeypatch, tmp_path):
    input_path = make_file(tmp_path, "in.wav")
    output_path = str(tmp_path / "out.wav")

    fake_tempfile = types.ModuleType("tempfile")

    def _no_mkdtemp(*args, **kwargs):
        raise AssertionError("no temp dir expected when both flags are off")

    fake_tempfile.mkdtemp = _no_mkdtemp
    monkeypatch.setattr("app.core.preprocess.tempfile", fake_tempfile)

    assert preprocess_audio(input_path, output_path, denoise=False, loudnorm=False) == input_path
    assert not os.path.exists(output_path)


def test_preprocess_denoise_only(monkeypatch, tmp_path):
    calls = {"denoise": [], "loudnorm": []}

    def _denoise(input_path, output_path, prop_decrease=0.75):
        calls["denoise"].append((input_path, output_path, prop_decrease))
        Path(output_path).write_bytes(b"denoised")

    def _loudnorm(input_path, output_path):
        calls["loudnorm"].append((input_path, output_path))

    monkeypatch.setattr("app.core.preprocess.denoise_audio", _denoise)
    monkeypatch.setattr("app.core.preprocess.normalize_loudness", _loudnorm)

    input_path = make_file(tmp_path, "in.wav")
    output_path = str(tmp_path / "out.wav")
    result = preprocess_audio(input_path, output_path, denoise=True, loudnorm=False)

    assert result == output_path
    assert len(calls["denoise"]) == 1
    denoise_input, denoise_tmp, prop = calls["denoise"][0]
    assert denoise_input == input_path
    assert denoise_tmp != output_path
    assert prop == 0.75
    assert calls["loudnorm"] == []
    assert os.path.exists(output_path)
    # the temp workdir is cleaned up
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".sfc-preprocess-")]
    assert leftovers == []


def test_preprocess_loudnorm_only(monkeypatch, tmp_path):
    calls = {"denoise": [], "loudnorm": []}

    def _denoise(input_path, output_path, prop_decrease=0.75):
        calls["denoise"].append((input_path, output_path))

    def _loudnorm(input_path, output_path):
        calls["loudnorm"].append((input_path, output_path))
        Path(output_path).write_bytes(b"loud")

    monkeypatch.setattr("app.core.preprocess.denoise_audio", _denoise)
    monkeypatch.setattr("app.core.preprocess.normalize_loudness", _loudnorm)

    input_path = make_file(tmp_path, "in.wav")
    output_path = str(tmp_path / "out.wav")
    result = preprocess_audio(input_path, output_path, denoise=False, loudnorm=True)

    assert result == output_path
    assert calls["denoise"] == []
    assert calls["loudnorm"] == [(input_path, output_path)]
    assert os.path.exists(output_path)


def test_preprocess_chains_denoise_then_loudnorm(monkeypatch, tmp_path):
    calls = {"denoise": [], "loudnorm": []}

    def _denoise(input_path, output_path, prop_decrease=0.75):
        calls["denoise"].append((input_path, output_path, prop_decrease))
        Path(output_path).write_bytes(b"denoised")

    def _loudnorm(input_path, output_path):
        calls["loudnorm"].append((input_path, output_path))
        Path(output_path).write_bytes(b"loud")

    monkeypatch.setattr("app.core.preprocess.denoise_audio", _denoise)
    monkeypatch.setattr("app.core.preprocess.normalize_loudness", _loudnorm)

    input_path = make_file(tmp_path, "in.wav")
    output_path = str(tmp_path / "out.wav")
    result = preprocess_audio(input_path, output_path, denoise=True, loudnorm=True)

    assert result == output_path
    denoise_input, denoise_tmp, _ = calls["denoise"][0]
    assert denoise_input == input_path
    # loudnorm consumes the denoised intermediate, not the original input
    assert calls["loudnorm"] == [(denoise_tmp, output_path)]


def test_preprocess_prop_decrease_passthrough(monkeypatch, tmp_path):
    captured: dict = {}

    def _denoise(input_path, output_path, prop_decrease=0.75):
        captured["prop"] = prop_decrease
        Path(output_path).write_bytes(b"x")

    monkeypatch.setattr("app.core.preprocess.denoise_audio", _denoise)
    monkeypatch.setattr("app.core.preprocess.normalize_loudness", lambda a, b: None)

    input_path = make_file(tmp_path, "in.wav")
    preprocess_audio(
        input_path,
        str(tmp_path / "out.wav"),
        denoise=True,
        loudnorm=False,
        prop_decrease=0.5,
    )
    assert captured["prop"] == 0.5
