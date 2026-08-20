#!/usr/bin/env python3
"""Sub for Creator — standalone subtitle CLI.

Runs the full pipeline on a local media file:
probe -> extract audio -> transcribe -> segment -> export
with optional burn-in to MP4.

Usage:
    python cli/subforcreator.py video.mp4 --lang zh --output out.srt
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

# --- Bootstrap: make the backend/ package importable ---------------------
_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

try:
    from app.core import (
        SFCError,
        TranscriptionResult,
        extract_audio,
        get_backend,
        probe_duration,
        probe_media,
        segment_words,
    )
    from app.exporters import (
        AssStyle,
        export_ass,
        export_fcpxml,
        export_srt,
        export_text,
        export_vtt,
    )
except ImportError as exc:  # pragma: no cover
    print(
        f"error: could not import backend package (looked in {_BACKEND_DIR}): {exc}",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    import tqdm
except ImportError:  # optional dependency — progress simply falls back to step prints
    tqdm = None

__version__ = "0.1.0"

FORMATS = ("srt", "vtt", "txt", "ass", "fcpxml", "json")


# --- helpers ---------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="subforcreator",
        description="Generate subtitles from a video or audio file with AI transcription.",
    )
    p.add_argument("input", type=Path, help="input media file (video or audio)")
    p.add_argument(
        "--lang", "-l", default=None,
        help="language code (ISO 639-1) to FORCE, e.g. zh/en/ja/ko; "
        "'auto' or omit = auto-detect",
    )
    p.add_argument("--output", "-o", type=Path, default=None, help="output file path")
    p.add_argument(
        "--format", "-f", choices=FORMATS, default=None,
        help="output format; default: inferred from --output extension, else srt",
    )
    p.add_argument(
        "--tier", choices=("lite", "standard", "pro"), default=None,
        help="accuracy tier: lite (small/int8), standard (medium), pro (large-v3); "
        "default: SFC_TIER env or standard",
    )
    p.add_argument(
        "--model", default=None,
        help="ASR model size override (wins over --tier); default: tier preset",
    )
    p.add_argument(
        "--beam-size", type=int, default=None,
        help="decoding beam size (default: tier preset: 5 lite/standard, 10 pro)",
    )
    p.add_argument(
        "--temperature", type=float, default=None,
        help="decoding temperature; 0 = deterministic (default: 0)",
    )
    p.add_argument(
        "--no-vad", action="store_true",
        help="disable voice-activity detection (VAD); default: enabled",
    )
    p.add_argument(
        "--max-line-chars", type=int, default=None,
        help="max characters per subtitle line (backend default if omitted)",
    )
    p.add_argument("--karaoke", action="store_true", help="ass only: karaoke word highlighting")
    p.add_argument(
        "--burn", action="store_true",
        help="render subtitles burned into an MP4 (format option is ignored)",
    )
    p.add_argument("--font-size", type=int, default=64)
    p.add_argument("--font-color", default="#FFFFFF")
    p.add_argument("--outline-color", default="#000000")
    p.add_argument("--font-family", default="Noto Sans CJK TC")
    p.add_argument("--position", choices=("bottom", "top"), default="bottom")
    p.add_argument(
        "--mock", action="store_true",
        help="use the mock ASR backend (for machines without a GPU)",
    )
    p.add_argument("--quiet", "-q", action="store_true", help="suppress progress output")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _attr(info, name, default=None):
    """Read an attribute from a dict or an object — probe_media return type is flexible."""
    if isinstance(info, dict):
        return info.get(name, default)
    return getattr(info, name, default)


def step(index, total, message, quiet) -> None:
    if not quiet:
        print(f"[{index}/{total}] {message}", file=sys.stderr, flush=True)


def media_summary(info) -> str:
    duration = _attr(info, "duration") or 0.0
    resolution = _attr(info, "resolution")
    if resolution is None:
        width = _attr(info, "width")
        height = _attr(info, "height")
        if width is not None and height is not None:
            resolution = f"{width}x{height}"
    return f"Duration: {duration:.1f}s  Resolution: {resolution or 'unknown'}"


def make_style(args) -> AssStyle:
    return AssStyle(
        font_size=args.font_size,
        primary_color=args.font_color,
        outline_color=args.outline_color,
        font_name=args.font_family,
        alignment=8 if args.position == "top" else 2,
    )


def render_output(result, fmt, args) -> str:
    """Serialize a TranscriptionResult for the requested text format."""
    if fmt == "srt":
        return export_srt(result)
    if fmt == "vtt":
        return export_vtt(result)
    if fmt == "txt":
        return export_text(result)
    if fmt == "ass":
        return export_ass(result, style=make_style(args), karaoke=args.karaoke)
    if fmt == "fcpxml":
        return export_fcpxml(result)
    return json.dumps(  # json
        [
            {
                "id": seg.id,
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
                "words": [{"text": w.text, "start": w.start, "end": w.end} for w in seg.words],
            }
            for seg in result.segments
        ],
        indent=2,
    )


def burn_subtitles(args, ass_text, workdir, has_audio) -> None:
    """Write a temp .ass file and burn it into args.output with ffmpeg."""
    ass_path = Path(workdir) / "burn.ass"
    ass_path.write_text(ass_text, encoding="utf-8", newline="\n")
    # Escape the path for use inside an ffmpeg filter graph.
    escaped = str(ass_path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    cmd = [
        "ffmpeg", "-y", "-i", str(args.input),
        "-vf", f"ass={escaped}",
        "-c:v", "libx264", "-crf", "20", "-preset", "medium",
    ]
    if has_audio:
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-an"]
    cmd.append(str(args.output))
    subprocess.run(cmd, check=True)


def run(args) -> int:
    if shutil.which("ffmpeg") is None:
        print(
            "error: ffmpeg not found on PATH — required for audio extraction and burn-in.",
            file=sys.stderr,
        )
        return 1
    if not args.input.exists():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 1

    # --- Resolve output format and path ------------------------------------
    if args.burn:
        fmt = "ass"
        if args.output is None:
            args.output = args.input.with_name(args.input.stem + ".burned.mp4")
    else:
        fmt = args.format
        if fmt is None:
            suffix = args.output.suffix.lstrip(".") if args.output else ""
            fmt = suffix if suffix in FORMATS else "srt"
        if args.output is None:
            args.output = args.input.with_suffix(f".{fmt}")
    args.output = Path(args.output)

    # --- Probe --------------------------------------------------------------
    try:
        info = probe_media(str(args.input))
    except SFCError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    duration = _attr(info, "duration")
    if duration is None:
        duration = probe_duration(str(args.input))
    has_audio = _attr(info, "has_audio", True)
    if not args.quiet:
        print(f"Input: {args.input}  {media_summary(info)}", file=sys.stderr, flush=True)

    total = 5 if args.burn else 4
    step(1, total, "Extracting audio...", args.quiet)
    workdir = tempfile.mkdtemp(prefix="sfc-cli-")
    try:
        wav_path = Path(workdir) / "audio.wav"
        extract_audio(str(args.input), str(wav_path))

        step(2, total, "Transcribing...", args.quiet)
        backend = get_backend(
            "mock" if args.mock else None,
            tier=args.tier,
            model_size=args.model,
            beam_size=args.beam_size,
            temperature=args.temperature,
            vad_enabled=False if args.no_vad else None,
        )
        if not args.quiet and tqdm is not None:
            with tqdm.tqdm(total=1, desc="  transcribe", leave=False) as bar:
                raw = backend.transcribe(str(wav_path), language=args.lang)
                bar.update(1)
        else:
            raw = backend.transcribe(str(wav_path), language=args.lang)

        step(3, total, "Segmenting...", args.quiet)
        segments = segment_words(
            raw.all_words(), raw.language, max_chars=args.max_line_chars
        )
        result = TranscriptionResult(
            segments=segments,
            language=raw.language,
            language_probability=raw.language_probability,
            media_duration=duration,
            model_size=backend.model_size,
        )

        step(4, total, "Exporting...", args.quiet)
        if args.burn:
            ass_text = export_ass(result, style=make_style(args), karaoke=args.karaoke)
            step(5, total, "Burning subtitles...", args.quiet)
            burn_subtitles(args, ass_text, workdir, has_audio)
        else:
            text = render_output(result, fmt, args)
            args.output.write_text(text, encoding="utf-8", newline="\n")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print(f"Saved: {args.output}")
    print(f"Segments: {len(result.segments)}  Language: {result.language}")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except SFCError as exc:
        message = str(exc).strip()
        if not message:
            message = exc.__class__.__name__
        print(f"error: {message}", file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - CLI top-level handler: report unexpected failures
        if not args.quiet:
            traceback.print_exc()
        print("error: unexpected failure", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
