"""Chunked upload sessions — work around proxies with small request-body caps.

Some port-forwarding proxies (e.g. GitHub Codespaces ``*.app.github.dev``)
reject single requests above a few MB. Splitting the file into small chunks
keeps every request well under the cap while still landing in the same
``POST /api/jobs`` pipeline.

Flow:
  POST   /jobs/uploads                     → {upload_id}
  POST   /jobs/uploads/{id}/chunks         → append one chunk (index + data)
  POST   /jobs/uploads/{id}/complete       → probe/quota/enqueue → job response
  DELETE /jobs/uploads/{id}                → abort, drop partial upload

Chunk state lives in ``<upload_dir>/.chunks/<upload_id>/`` and is swept by
the regular TTL cleanup when abandoned.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import session_token
from app.api.jobs import _finalize_upload
from app.api.limits import check_upload_rate
from app.config import Settings, get_settings
from app.database import get_db

log = logging.getLogger(__name__)

router = APIRouter()

#: subdirectory under SFC_UPLOAD_DIR holding in-progress chunk sessions
CHUNKS_SUBDIR = ".chunks"

META_NAME = "meta.json"


def _session_dir(settings: Settings, upload_id: str) -> str:
    return os.path.join(settings.upload_dir, CHUNKS_SUBDIR, upload_id)


def _load_meta(settings: Settings, upload_id: str) -> dict:
    meta_path = os.path.join(_session_dir(settings, upload_id), META_NAME)
    try:
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="upload session not found") from None
    if not isinstance(meta, dict):
        raise HTTPException(status_code=404, detail="upload session not found")
    return meta


def _save_meta(settings: Settings, upload_id: str, meta: dict) -> None:
    meta_path = os.path.join(_session_dir(settings, upload_id), META_NAME)
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh)


def _drop_session(settings: Settings, upload_id: str) -> None:
    shutil.rmtree(_session_dir(settings, upload_id), ignore_errors=True)


@router.post("/jobs/uploads")
def start_upload(
    filename: str = Form(...),
    language: str | None = Form(None),
    options: str | None = Form(None),
    token: str = Depends(session_token),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Create an upload session and return its ``upload_id``."""
    safe_name = os.path.basename(filename) or "upload"
    upload_id = uuid.uuid4().hex
    session_dir = _session_dir(settings, upload_id)
    os.makedirs(session_dir, exist_ok=True)
    try:
        _save_meta(
            settings,
            upload_id,
            {
                "filename": safe_name,
                "language": language,
                "options": options,
                "token": token,
                "created_at": time.time(),
            },
        )
    except OSError:
        _drop_session(settings, upload_id)
        raise HTTPException(status_code=500, detail="failed to create upload session") from None
    return {"upload_id": upload_id}


@router.post("/jobs/uploads/{upload_id}/chunks")
def append_chunk(
    upload_id: str,
    index: int = Form(...),
    data: UploadFile = File(...),
    token: str = Depends(session_token),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Append one chunk of the file. Chunks are written sequentially."""
    if index < 0:
        raise HTTPException(status_code=422, detail="chunk index must be >= 0")
    meta = _load_meta(settings, upload_id)
    if meta.get("token") != token:
        raise HTTPException(
            status_code=403, detail="upload session belongs to another session"
        )
    ext = os.path.splitext(meta["filename"])[1].lower() or ".bin"
    part_path = os.path.join(_session_dir(settings, upload_id), f"part{ext}")
    try:
        with open(part_path, "ab") as fh:
            while chunk := data.file.read(1024 * 1024):
                fh.write(chunk)
    except OSError:
        raise HTTPException(status_code=500, detail="failed to write chunk") from None
    return {"ok": True, "received": index}


@router.post("/jobs/uploads/{upload_id}/complete")
def complete_upload(
    upload_id: str,
    token: str = Depends(session_token),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Assemble the received chunks and feed the normal job pipeline."""
    check_upload_rate(token)
    meta = _load_meta(settings, upload_id)
    if meta.get("token") != token:
        raise HTTPException(
            status_code=403, detail="upload session belongs to another session"
        )
    ext = os.path.splitext(meta["filename"])[1].lower() or ".bin"
    part_path = os.path.join(_session_dir(settings, upload_id), f"part{ext}")
    try:
        size = os.path.getsize(part_path)
    except OSError:
        raise HTTPException(status_code=422, detail="upload session is empty") from None
    if size == 0:
        raise HTTPException(status_code=422, detail="empty file")

    max_bytes = int(settings.max_upload_mb * 1024 * 1024)
    if max_bytes > 0 and size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"file exceeds maximum upload size of {settings.max_upload_mb} MB"
            ),
        )

    try:
        return _finalize_upload(
            part_path,
            meta["filename"],
            token,
            meta.get("language"),
            meta.get("options"),
            db,
            settings,
        )
    finally:
        _drop_session(settings, upload_id)


@router.delete("/jobs/uploads/{upload_id}")
def abort_upload(
    upload_id: str,
    token: str = Depends(session_token),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Abort an in-progress upload session and drop its partial data."""
    meta = _load_meta(settings, upload_id)
    if meta.get("token") != token:
        raise HTTPException(
            status_code=403, detail="upload session belongs to another session"
        )
    _drop_session(settings, upload_id)
    return {"ok": True}
