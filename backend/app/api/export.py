"""GET /api/jobs/{job_id}/export/{format} — text exports and burned-in renders.

Text formats (srt/vtt/txt/ass/fcpxml) are generated synchronously from the
stored segments. mp4/webm_alpha burn the ASS subtitles into the source video
with ffmpeg; renders are cached per job and guarded by a per-job lock so two
concurrent requests never render twice.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import ensure_not_expired, get_job_or_404, require_done, session_token
from app.config import Settings, get_settings
from app.core.exceptions import RenderError
from app.core.models import TranscriptionResult
from app.database import get_db
from app.exporters import AssStyle, export_ass, export_fcpxml, export_srt, export_text, export_vtt
from app.models.db import Job
from app.storage import get_storage, render_key, source_key
from app.worker.serialization import json_to_segments

router = APIRouter()

TEXT_FORMATS = {"srt", "vtt", "txt", "ass", "fcpxml"}
RENDER_FORMATS = {
    "mp4": ("burned.mp4", "video/mp4"),
    "webm_alpha": ("alpha.webm", "video/webm"),
}
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")

_render_locks: dict[str, threading.Lock] = {}
_render_locks_guard = threading.Lock()


def _render_lock(job_id: str) -> threading.Lock:
    with _render_locks_guard:
        if job_id not in _render_locks:
            _render_locks[job_id] = threading.Lock()
        return _render_locks[job_id]


def _build_result(job: Job) -> TranscriptionResult:
    return TranscriptionResult(
        segments=json_to_segments(job.segments_json) if job.segments_json else [],
        language=job.language or "und",
        media_duration=job.duration,
        model_size=job.model_size,
    )


def _build_style(
    font_size: int,
    font_color: str,
    outline_color: str,
    font_family: str | None,
    position: str,
) -> AssStyle:
    if not _HEX_COLOR.match(font_color):
        raise HTTPException(status_code=422, detail="font_color must be #RRGGBB")
    if not _HEX_COLOR.match(outline_color):
        raise HTTPException(status_code=422, detail="outline_color must be #RRGGBB")
    if position not in ("bottom", "top"):
        raise HTTPException(status_code=422, detail="position must be 'bottom' or 'top'")
    kwargs: dict = {
        "font_size": font_size,
        "primary_color": font_color,
        "outline_color": outline_color,
        "alignment": 2 if position == "bottom" else 8,
    }
    if font_family:
        kwargs["font_name"] = font_family
    return AssStyle(**kwargs)


def _stem(job: Job) -> str:
    return os.path.splitext(os.path.basename(job.filename))[0] or "subtitle"


def _text_response(content: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _export_text(job: Job, fmt: str, settings: Settings, **params) -> Response:
    result = _build_result(job)
    stem = _stem(job)
    if fmt == "srt":
        return _text_response(export_srt(result), f"{stem}.srt")
    if fmt == "vtt":
        return _text_response(export_vtt(result), f"{stem}.vtt")
    if fmt == "txt":
        return _text_response(
            export_text(result, include_punctuation=params["include_punctuation"]),
            f"{stem}.txt",
        )
    if fmt == "ass":
        style = _build_style(
            params["font_size"],
            params["font_color"],
            params["outline_color"],
            params["font_family"],
            params["position"],
        )
        return _text_response(
            export_ass(result, style=style, karaoke=params["karaoke"]), f"{stem}.ass"
        )
    return _text_response(export_fcpxml(result), f"{stem}.fcpxml")


def _has_audio(path: str) -> bool:
    """True when the source has an audio stream (drives -c:a copy vs -an)."""
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True  # unknown -> try copying; ffmpeg tolerates a missing stream
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _ffmpeg_cmd(source: str, ass_path: str, out: str, fmt: str, has_audio: bool) -> list[str]:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RenderError("ffmpeg not available")
    escaped = ass_path.replace("\\", "\\\\").replace(":", "\\:")
    cmd = [ffmpeg, "-y", "-i", source, "-vf", f"ass={escaped}"]
    if fmt == "mp4":
        cmd += ["-c:v", "libx264", "-crf", "20", "-preset", "medium"]
        cmd += ["-c:a", "copy"] if has_audio else ["-an"]
        cmd += ["-movflags", "+faststart"]
    else:  # webm_alpha
        cmd += ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "30", "-an"]
    cmd.append(out)
    return cmd


def _render(job: Job, fmt: str, settings: Settings, **params) -> FileResponse:
    kind, media_type = RENDER_FORMATS[fmt]
    storage = get_storage()
    key = render_key(job.id, kind)
    stem = _stem(job)
    filename = f"{stem}.{kind.split('.')[-1]}"

    def _file_response() -> FileResponse:
        return FileResponse(
            storage.open_path(key),
            media_type=media_type,
            filename=filename,
            content_disposition_type="attachment",
        )

    if storage.exists(key):
        return _file_response()

    with _render_lock(job.id):
        if storage.exists(key):
            return _file_response()

        style = _build_style(
            params["font_size"],
            params["font_color"],
            params["outline_color"],
            params["font_family"],
            params["position"],
        )
        result = _build_result(job)
        ass_text = export_ass(result, style=style, karaoke=params["karaoke"])

        tmpdir = tempfile.mkdtemp(prefix="sfc-render-")
        try:
            ass_path = os.path.join(tmpdir, "subtitle.ass")
            with open(ass_path, "w", encoding="utf-8") as fh:
                fh.write(ass_text)

            ext = os.path.splitext(job.filename)[1].lower() or ".bin"
            source = storage.open_path(source_key(job.id, ext))
            out = storage.writable_path(key)
            cmd = _ffmpeg_cmd(source, ass_path, out, fmt, _has_audio(source))
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=settings.render_timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                raise RenderError("render timeout") from exc
            if proc.returncode != 0:
                raise RenderError(f"ffmpeg render failed: {proc.stderr[-500:]}")
            storage.save(out, key)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return _file_response()


@router.get("/jobs/{job_id}/export/{fmt}")
def export_job(
    job_id: str,
    fmt: str,
    token: str = Depends(session_token),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    font_size: int = Query(64, ge=1),
    font_color: str = Query("#FFFFFF"),
    outline_color: str = Query("#000000"),
    font_family: str | None = Query(None),
    karaoke: str = Query("0"),
    position: str = Query("bottom"),
    include_punctuation: bool = Query(True),
) -> Response:
    if fmt not in TEXT_FORMATS and fmt not in RENDER_FORMATS:
        raise HTTPException(status_code=422, detail=f"invalid export format {fmt!r}")
    if karaoke not in ("0", "1"):
        raise HTTPException(status_code=422, detail="karaoke must be 0 or 1")

    job = get_job_or_404(db, job_id)
    ensure_not_expired(db, job)
    require_done(job)

    params = {
        "font_size": font_size,
        "font_color": font_color,
        "outline_color": outline_color,
        "font_family": font_family,
        "karaoke": karaoke == "1",
        "position": position,
        "include_punctuation": include_punctuation,
    }
    if fmt in TEXT_FORMATS:
        return _export_text(job, fmt, settings, **params)
    return _render(job, fmt, settings, **params)
