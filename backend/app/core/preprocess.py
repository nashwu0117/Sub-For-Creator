"""Audio preprocessing: denoising and loudness normalization.

Both steps are optional and chained by ``preprocess_audio``. Heavy third-party
deps (noisereduce, scipy) are imported lazily inside the functions that need
them so importing this module never pulls them in.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile

from .exceptions import AudioExtractionError

logger = logging.getLogger(__name__)


def _require(binary: str) -> str:
    path = shutil.which(binary)
    if path is None:
        raise AudioExtractionError(
            f"{binary} not found; install ffmpeg to process media files"
        )
    return path


def _run(cmd: list[str], context: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        detail = stderr[-500:] if stderr else "no stderr output"
        raise AudioExtractionError(f"{context}: {detail}")
    return proc


def denoise_audio(input_path: str, output_path: str, prop_decrease: float = 0.75) -> None:
    """Apply stationary spectral-gate noise reduction to a 16 kHz mono WAV.

    Accepts int16 or float32 WAV data (via scipy.io.wavfile) and writes an
    int16 WAV to ``output_path``. Raises AudioExtractionError on any failure.
    """
    try:
        import noisereduce as nr
        from scipy.io import wavfile
    except ImportError as exc:
        raise AudioExtractionError(
            f"noisereduce/scipy not installed; cannot denoise {input_path!r}"
        ) from exc
    try:
        sr, data = wavfile.read(input_path)
        y = (
            data.astype("float32") / 32768.0
            if data.dtype == "int16"
            else data.astype("float32")
        )
        reduced = nr.reduce_noise(
            y=y,
            sr=sr,
            prop_decrease=prop_decrease,
            stationary=True,
            n_std_thresh_stationary=1.5,
        )
        out = (reduced * 32768.0).clip(-32768, 32767).astype("int16")
        wavfile.write(output_path, sr, out)
    except Exception as exc:  # noqa: BLE001 - wrap any failure as AudioExtractionError
        raise AudioExtractionError(f"denoising failed for {input_path!r}: {exc}") from exc


def normalize_loudness(input_path: str, output_path: str) -> None:
    """Normalize loudness to -16 LUFS via ffmpeg loudnorm (16 kHz mono s16le).

    Raises AudioExtractionError on nonzero exit (stderr tail included).
    """
    ffmpeg = _require("ffmpeg")
    _run(
        [
            ffmpeg,
            "-y",
            "-i",
            input_path,
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            output_path,
        ],
        f"loudness normalization failed for {input_path!r}",
    )


def preprocess_audio(
    input_path: str,
    output_path: str,
    *,
    denoise: bool,
    loudnorm: bool,
    prop_decrease: float = 0.75,
) -> str:
    """Chain denoising and/or loudness normalization; return the final path.

    When neither flag is set the input path is returned unchanged. Temp files
    are created in the output directory and cleaned up in a finally block.
    """
    if not denoise and not loudnorm:
        return input_path
    out_dir = os.path.dirname(os.path.abspath(output_path))
    workdir = tempfile.mkdtemp(dir=out_dir, prefix=".sfc-preprocess-")
    try:
        current = input_path
        if denoise:
            tmp1 = os.path.join(workdir, "denoised.wav")
            denoise_audio(current, tmp1, prop_decrease=prop_decrease)
            current = tmp1
        if loudnorm:
            normalize_loudness(current, output_path)
        else:
            os.replace(current, output_path)
        return output_path
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
