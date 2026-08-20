"""GET/POST /api/jobs/{job_id}/export/{format} — text exports and burned-in renders.

Text formats (srt/vtt/txt/ass/fcpxml) are generated synchronously from the
stored segments. mp4/webm_alpha burn the ASS subtitles into the source video
with ffmpeg; encodes can take minutes, so they run in a background thread
instead of holding the request open (a long synchronous request would be
killed by proxy read timeouts, e.g. nginx 504). Renders are cached per job.
The render lifecycle:

    POST /jobs/{id}/export/{fmt}/render   → start the encode (or "ready" if cached)
    GET  /jobs/{id}/export/{fmt}/status   → {status: idle|rendering|ready|failed}
    GET  /jobs/{id}/export/{fmt}          → download the finished file (409 until ready)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import (
    current_user,
    ensure_not_expired,
    get_job_or_404,
    require_done,
    require_job_access,
    session_token,
)
from app.config import Settings, get_settings
from app.core import MediaProcessingError, probe_media
from app.core.exceptions import RenderError
from app.core.models import TranscriptionResult
from app.database import SessionLocal, get_db
from app.exporters import (
    AssStyle,
    export_ass,
    export_capcut,
    export_fcpxml,
    export_srt,
    export_text,
    export_vtt,
)
from app.models.db import Job, User
from app.storage import get_storage, render_key, source_key
from app.worker.serialization import json_to_segments

router = APIRouter()

TEXT_FORMATS = {"srt", "vtt", "txt", "ass", "fcpxml", "capcut"}
RENDER_FORMATS = {
    "mp4": ("burned.mp4", "video/mp4"),
    "webm_alpha": ("alpha.webm", "video/webm"),
}
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")

_render_locks: dict[str, threading.Lock] = {}
_render_locks_guard = threading.Lock()

#: In-memory render progress: (job_id, fmt) -> {"status", "started", "error"}.
#: Only tracks in-flight renders; "ready" is derived from the cached file.
_RENDER_STATES: dict[tuple[str, str], dict] = {}
_RENDER_STATES_GUARD = threading.Lock()


def _render_lock(job_id: str) -> threading.Lock:
    with _render_locks_guard:
        if job_id not in _render_locks:
            _render_locks[job_id] = threading.Lock()
        return _render_locks[job_id]


def _set_render_state(job_id: str, fmt: str, status: str, error: str | None = None) -> None:
    with _RENDER_STATES_GUARD:
        _RENDER_STATES[(job_id, fmt)] = {
            "status": status,
            "started": time.time(),
            "error": error,
        }


def _get_render_state(job_id: str, fmt: str) -> dict | None:
    with _RENDER_STATES_GUARD:
        return _RENDER_STATES.get((job_id, fmt))


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


def _zip_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type="application/zip",
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
    if fmt == "capcut":
        return _zip_response(
            export_capcut(result, media_name=stem), f"{stem}_capcut_draft.zip"
        )
    return _text_response(export_fcpxml(result, media_name=stem), f"{stem}.fcpxml")


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


def _probe_fps(path: str) -> float:
    """Read the source video frame rate via ffprobe; 0.0 when unavailable."""
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=avg_frame_rate", "-of", "csv=p=0", path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        num, _, den = proc.stdout.strip().split("/")
        fps = float(num) / float(den) if float(den) else 0.0
        return fps if 1.0 <= fps <= 240.0 else 0.0
    except (OSError, subprocess.TimeoutExpired, ValueError, ZeroDivisionError):
        return 0.0


def _probe_video_meta(path: str) -> tuple[int, int, float]:
    """Probe source video dimensions and frame rate for the transparent render.

    Falls back to 1920x1080@30 when probing fails (e.g. audio-only source).
    """
    width, height, fps = 1920, 1080, 30.0
    try:
        info = probe_media(path)
        if info.get("width") and info.get("height"):
            width, height = info["width"], info["height"]
    except MediaProcessingError:
        pass
    return width, height, _probe_fps(path) or fps


def _ffmpeg_cmd(
    source: str,
    ass_path: str,
    out: str,
    fmt: str,
    has_audio: bool,
    width: int = 1920,
    height: int = 1080,
    fps: float = 30.0,
    duration: float = 0.0,
) -> list[str]:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RenderError("ffmpeg not available")
    escaped = ass_path.replace("\\", "\\\\").replace(":", "\\:")
    if fmt == "mp4":
        cmd = [ffmpeg, "-y", "-i", source, "-vf", f"ass={escaped}"]
        cmd += ["-c:v", "libx264", "-crf", "20", "-preset", "faster"]
        cmd += ["-c:a", "copy"] if has_audio else ["-an"]
        cmd += ["-movflags", "+faststart", "-f", "mp4"]
    else:  # webm_alpha — subtitles on a fully transparent canvas, no source video
        # Verified on ffmpeg 6.1 + libvpx 1.14: the `color` source ignores
        # alpha syntax (black@0.0 is opaque) and the ass filter passes the
        # input alpha through untouched instead of painting subtitle alpha,
        # so the solid black canvas is rendered first and the black backdrop
        # is then keyed out with colorkey. libvpx-vp9 stores alpha as a
        # second stream only when -auto-alt-ref 0 is set (VP9-alpha WebM).
        cmd = [
            ffmpeg, "-y", "-f", "lavfi", "-i",
            f"color=c=black:s={width}x{height}:r={fps}:d={max(0.1, duration)}",
            "-vf",
            f"ass={escaped},format=rgba,colorkey=black:0.15:0.0,format=yuva420p",
            "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
            "-auto-alt-ref", "0", "-b:v", "0", "-crf", "30", "-an",
            "-f", "webm",
        ]
    cmd.append(out)
    return cmd


def _run_render(job: Job, fmt: str, settings: Settings, params: dict, out_key: str) -> None:
    """Encode burned-in subtitles to ``out_key`` (temp file + atomic rename).

    The output is written to a ``.tmp`` sibling and renamed into place only
    after ffmpeg succeeds, so a partial file never shows up as a finished
    render (e.g. after a crash mid-encode).
    """
    storage = get_storage()
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
        out = storage.writable_path(out_key)
        tmp_out = f"{out}.{os.getpid()}.tmp"
        if os.path.exists(tmp_out):
            os.unlink(tmp_out)
        if fmt == "webm_alpha":
            width, height, fps = _probe_video_meta(source)
            duration = job.duration or 0.0
        else:
            width = height = 1920
            fps, duration = 30.0, 0.0
        cmd = _ffmpeg_cmd(
            source, ass_path, tmp_out, fmt, _has_audio(source),
            width=width, height=height, fps=fps, duration=duration,
        )
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
        os.replace(tmp_out, out)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _render_worker(job_id: str, fmt: str, settings: Settings, params: dict) -> None:
    """Background encode; always writes a terminal state for the status endpoint."""
    try:
        with SessionLocal() as db:
            job = get_job_or_404(db, job_id)
            key = render_key(job.id, RENDER_FORMATS[fmt][0])
            if not get_storage().exists(key):
                _run_render(job, fmt, settings, params, key)
        _set_render_state(job_id, fmt, "ready")
    except Exception as exc:  # noqa: BLE001 — surface any failure via /status
        _set_render_state(job_id, fmt, "failed", str(exc))


def start_render(job: Job, fmt: str, settings: Settings, params: dict) -> str:
    """Start a background render if needed; returns the resulting status."""
    key = render_key(job.id, RENDER_FORMATS[fmt][0])
    if get_storage().exists(key):
        _set_render_state(job.id, fmt, "ready")
        return "ready"
    state = _get_render_state(job.id, fmt)
    if state and state["status"] == "rendering":
        return "rendering"
    _set_render_state(job.id, fmt, "rendering")
    # Clear any stale cross-process failure marker from a previous attempt
    err_key = render_key(job.id, f"{RENDER_FORMATS[fmt][0]}.error")
    get_storage().save(b"", err_key)
    from app.worker.render_tasks import render_task  # lazy import

    try:
        render_task.delay(job.id, fmt, params)
    except Exception:
        # broker unreachable — fall back to the in-process thread so renders
        # keep working without Redis (mirrors the inline-queue fallback)
        thread = threading.Thread(
            target=_render_worker,
            args=(job.id, fmt, settings, params),
            name=f"sfc-render-{job.id}-{fmt}",
            daemon=True,
        )
        thread.start()
    return "rendering"


def render_status(job_id: str, fmt: str, settings: Settings) -> tuple[str, str | None]:
    """Current render state: ready (cached file), rendering, failed, or idle."""
    # The render task runs in a Celery worker process, so terminal states
    # derived from storage take precedence over the local in-memory hint.
    if get_storage().exists(render_key(job_id, RENDER_FORMATS[fmt][0])):
        _set_render_state(job_id, fmt, "ready")
        return "ready", None
    err_key = render_key(job_id, f"{RENDER_FORMATS[fmt][0]}.error")
    if get_storage().exists(err_key):
        try:
            with open(get_storage().open_path(err_key), encoding="utf-8") as fh:
                error = fh.read()
        except OSError:
            error = ""
        if error:
            _set_render_state(job_id, fmt, "failed")
            return "failed", error
    state = _get_render_state(job_id, fmt)
    if state and state["status"] == "rendering":
        # A worker can die without writing a terminal state (e.g. API restart);
        # after the render budget elapses, fall through to the cache check.
        if time.time() - state["started"] > settings.render_timeout_seconds + 120:
            _set_render_state(job_id, fmt, "idle")
        else:
            return "rendering", None
    if state and state["status"] == "failed":
        return "failed", state.get("error")
    return "idle", None


def _render_params(
    font_size: int,
    font_color: str,
    outline_color: str,
    font_family: str | None,
    karaoke: bool,
    position: str,
) -> dict:
    return {
        "font_size": font_size,
        "font_color": font_color,
        "outline_color": outline_color,
        "font_family": font_family,
        "karaoke": karaoke,
        "position": position,
    }


def _validate_render_format(fmt: str) -> None:
    if fmt not in RENDER_FORMATS:
        raise HTTPException(status_code=422, detail=f"invalid render format {fmt!r}")


@router.post("/jobs/{job_id}/export/{fmt}/render")
def start_export_render(
    job_id: str,
    fmt: str,
    token: str = Depends(session_token),
    user: User | None = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    font_size: int = Query(64, ge=1),
    font_color: str = Query("#FFFFFF"),
    outline_color: str = Query("#000000"),
    font_family: str | None = Query(None),
    karaoke: str = Query("0"),
    position: str = Query("bottom"),
) -> dict:
    """Start (or resume) a background burn-in encode; returns its status."""
    _validate_render_format(fmt)
    if karaoke not in ("0", "1"):
        raise HTTPException(status_code=422, detail="karaoke must be 0 or 1")
    job = get_job_or_404(db, job_id)
    ensure_not_expired(db, job)
    require_done(job)
    require_job_access(db, job, user, token)
    status = start_render(
        job,
        fmt,
        settings,
        _render_params(font_size, font_color, outline_color, font_family, karaoke == "1", position),
    )
    return {"status": status}


@router.get("/jobs/{job_id}/export/{fmt}/status")
def export_render_status(
    job_id: str,
    fmt: str,
    token: str = Depends(session_token),
    user: User | None = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Render progress: ``idle`` | ``rendering`` | ``ready`` | ``failed``."""
    _validate_render_format(fmt)
    job = get_job_or_404(db, job_id)
    require_done(job)
    require_job_access(db, job, user, token)
    status, error = render_status(job_id, fmt, settings)
    return {"status": status, "error": error}


@router.get("/jobs/{job_id}/export/{fmt}")
def export_job(
    job_id: str,
    fmt: str,
    token: str = Depends(session_token),
    user: User | None = Depends(current_user),
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
    """Download an export. Text formats are generated on the fly; render
    formats return the cached encode (``409`` until ``POST .../render``
    finishes)."""
    if fmt not in TEXT_FORMATS and fmt not in RENDER_FORMATS:
        raise HTTPException(status_code=422, detail=f"invalid export format {fmt!r}")
    if karaoke not in ("0", "1"):
        raise HTTPException(status_code=422, detail="karaoke must be 0 or 1")

    job = get_job_or_404(db, job_id)
    ensure_not_expired(db, job)
    require_done(job)
    require_job_access(db, job, user, token)

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

    kind, media_type = RENDER_FORMATS[fmt]
    storage = get_storage()
    key = render_key(job.id, kind)
    if not storage.exists(key):
        raise HTTPException(
            status_code=409,
            detail="render not ready; POST /jobs/{job_id}/export/{fmt}/render first",
        )
    stem = _stem(job)
    filename = f"{stem}.{kind.split('.')[-1]}"
    return FileResponse(
        storage.open_path(key),
        media_type=media_type,
        filename=filename,
        content_disposition_type="attachment",
    )
