"""GET/POST /api/fonts — custom font uploads for burn-in rendering.

Fonts are stored under the ``fonts/`` storage prefix and mirrored into
``~/.fonts`` via fontconfig so ffmpeg/libass can use them in MP4/WebM
renders. Uploads are anonymous-session scoped like every other endpoint.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.api.deps import session_token
from app.config import Settings, get_settings
from app.core.fonts import FONT_EXTENSIONS, register_font, sanitize_font_filename
from app.storage import Storage, get_storage

router = APIRouter()

_FONTS_PREFIX = "fonts/"


def _list_fonts(storage: Storage) -> list[dict]:
    """Storage entries under ``fonts/`` as API payload dicts (sorted by name)."""
    fonts: list[dict] = []
    for key in storage.list(_FONTS_PREFIX):
        stat = storage.stat(key)
        if stat is None:
            continue
        size, mtime = stat
        filename = os.path.basename(key)
        fonts.append(
            {
                "name": os.path.splitext(filename)[0],
                "filename": filename,
                "size": size,
                "uploaded_at": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
            }
        )
    return sorted(fonts, key=lambda f: f["name"])


@router.get("/fonts")
def list_fonts(
    token: str = Depends(session_token),
) -> dict:
    """List uploaded fonts (name, filename, size, upload time)."""
    return {"fonts": _list_fonts(get_storage())}


@router.post("/fonts")
async def upload_font(
    file: UploadFile = File(...),
    token: str = Depends(session_token),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Upload a .ttf/.otf font; stored under ``fonts/`` and registered with fontconfig."""
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in FONT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="僅支援 .ttf / .otf 字型檔")

    max_bytes = settings.max_font_mb * 1024 * 1024
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"字型檔過大（上限 {settings.max_font_mb} MB）",
        )

    data = await file.read()
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"字型檔過大（上限 {settings.max_font_mb} MB）",
        )
    if not data:
        raise HTTPException(status_code=422, detail="empty file")

    name = sanitize_font_filename(filename)
    storage = get_storage()
    storage.save(data, f"{_FONTS_PREFIX}{name}")

    with tempfile.NamedTemporaryFile(prefix="sfc-font-", suffix=ext, delete=False) as tmp:
        tmp.write(data)
    try:
        register_font(Path(tmp.name))
    finally:
        os.unlink(tmp.name)

    return JSONResponse(
        status_code=201,
        content={"name": os.path.splitext(name)[0], "filename": name, "size": len(data)},
    )