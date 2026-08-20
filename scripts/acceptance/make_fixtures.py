#!/usr/bin/env python3
"""Generate audio fixtures for ASR accuracy acceptance tests.

Creates deterministic WAV fixtures under scripts/acceptance/fixtures/ using
ffmpeg lavfi sources plus espeak-ng speech synthesis (offline, no network).
The pure-tone fixtures exercise the pipeline mechanics (noise-floor math,
VAD gating), while the speech fixtures give the ASR model real content so the
determinism / dictionary / LLM scenarios produce non-empty transcripts.

Fixtures:
  silence.wav               15s pure digital silence        -> VAD hallucination contrast
  tone_silence_tone.wav     6s tone + 6s silence + 6s tone  -> VAD boundary test
  tone_clean.wav            8s 440Hz tone (clean)           -> denoise control
  tone_noisy.wav            8s 440Hz tone + 50% white noise -> denoise test (SNR ~0dB)
  tone_noisy_high.wav       8s 440Hz tone + 80% white noise -> denoise stress test
  speech.wav                espeak-ng spoken phrase         -> ASR content baseline
  speech_silence_speech.wav phrase + 4s silence + phrase    -> determinism / LLM test
  speech_noisy.wav          phrase + 50% white noise        -> denoise end-to-end test
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: spoken phrase used for all speech fixtures (en keeps the small model sharp)
PHRASE = "Hello world. This is a test of the subtitle system."


def ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", *args], check=True, capture_output=True)


def make_silence(out: Path) -> None:
    # 15s of true digital silence
    ffmpeg(
        [
            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
            "-t", "15", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            str(out),
        ]
    )


def make_tone_silence_tone(out: Path) -> None:
    # 6s tone + 6s silence + 6s tone
    ffmpeg(
        [
            "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
            "-af", "apad=pad_dur=12", "-t", "18",
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            str(out),
        ]
    )


def make_tone(out: Path) -> None:
    # ffmpeg sine source has a fixed 0.125 amplitude (~ -18dB RMS)
    ffmpeg(
        [
            "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            str(out),
        ]
    )


def make_noisy(out: Path, noise_volume: str) -> None:
    # quiet sine + loud white noise; normalize=0 keeps levels exact
    # (amix's default normalize=1 would attenuate the noise away)
    ffmpeg(
        [
            "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
            "-f", "lavfi", "-i", "anoisesrc=color=white:duration=8:sample_rate=16000:amplitude=0.5",
            "-filter_complex",
            f"[1:a]volume={noise_volume}dB[n];[0:a][n]amix=inputs=2:duration=first:normalize=0",
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            str(out),
        ]
    )


def make_speech(out: Path, phrase: str = PHRASE) -> None:
    # espeak-ng -> 16k mono WAV; deterministic given the same text + voice
    subprocess.run(
        [
            "espeak-ng", "-v", "en-us", "-s", "150", "-w", str(out), phrase,
        ],
        capture_output=True, text=True, check=True,
    )
    # normalize to 16k mono PCM (espeak-ng writes 22050 Hz by default)
    tmp = out.with_suffix(".raw.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(out), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(tmp)],
        capture_output=True, check=True,
    )
    tmp.replace(out)


def make_speech_silence_speech(out: Path) -> None:
    ffmpeg(
        [
            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
            "-t", "4", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            str(out.with_suffix(".sil.wav")),
        ]
    )
    make_speech(out.with_suffix(".a.wav"))
    make_speech(out.with_suffix(".b.wav"))
    ffmpeg(
        [
            "-i", str(out.with_suffix(".a.wav")),
            "-i", str(out.with_suffix(".sil.wav")),
            "-i", str(out.with_suffix(".b.wav")),
            "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1",
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            str(out),
        ]
    )
    out.with_suffix(".a.wav").unlink(missing_ok=True)
    out.with_suffix(".b.wav").unlink(missing_ok=True)
    out.with_suffix(".sil.wav").unlink(missing_ok=True)


def make_speech_noisy(out: Path) -> None:
    # amix normalize=0 keeps the noise level exact
    make_speech(out.with_suffix(".sp.wav"))
    ffmpeg(
        [
            "-i", str(out.with_suffix(".sp.wav")),
            "-f", "lavfi", "-i", "anoisesrc=color=white:duration=6:sample_rate=16000:amplitude=0.5",
            "-filter_complex", "[1:a]volume=-9dB[n];[0:a][n]amix=inputs=2:duration=first:normalize=0",
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            str(out),
        ]
    )
    out.with_suffix(".sp.wav").unlink(missing_ok=True)


def noise_floor_db(path: Path) -> float:
    """Return the mean volume (dB) of a WAV via ffmpeg volumedetect."""
    proc = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=False,
    )
    for line in proc.stderr.splitlines():
        if "mean_volume" in line:
            return float(line.split(":")[1].strip().replace(" dB", ""))
    raise RuntimeError(f"could not measure volume of {path}")


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    if shutil.which("ffmpeg") is None:
        print("error: ffmpeg required to generate fixtures", file=sys.stderr)
        return 1
    if shutil.which("espeak-ng") is None:
        print("error: espeak-ng required for speech fixtures (apt install espeak-ng)", file=sys.stderr)
        return 1

    make_silence(FIXTURES / "silence.wav")
    make_tone_silence_tone(FIXTURES / "tone_silence_tone.wav")
    make_tone(FIXTURES / "tone_clean.wav")
    make_noisy(FIXTURES / "tone_noisy.wav", "-3")
    make_noisy(FIXTURES / "tone_noisy_high.wav", "3")
    make_speech(FIXTURES / "speech.wav")
    make_speech_silence_speech(FIXTURES / "speech_silence_speech.wav")
    make_speech_noisy(FIXTURES / "speech_noisy.wav")

    print("fixtures written to", FIXTURES)
    for p in sorted(FIXTURES.glob("*.wav")):
        print(f"  {p.name}: {p.stat().st_size} bytes, mean_volume="
              f"{noise_floor_db(p):.1f} dB")
    return 0


if __name__ == "__main__":
    sys.exit(main())