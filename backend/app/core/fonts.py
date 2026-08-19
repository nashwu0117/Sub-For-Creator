"""Custom font upload support: filename sanitization and fontconfig registration.

Fonts live under the ``fonts/`` storage prefix and are mirrored into
``~/.fonts`` so ffmpeg/libass can resolve them during burn-in renders.
Registration is best-effort: failures are swallowed and reported as ``False``
(or skipped by :func:`sync_fonts`), never raised.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path

from app.storage import Storage

log = logging.getLogger(__name__)

#: Accepted font file extensions (lowercase, with leading dot).
FONT_EXTENSIONS = {".ttf", ".otf"}

#: Hard cap on sanitized filenames (keeps storage keys short and safe).
_MAX_FONT_FILENAME_LEN = 120


def sanitize_font_filename(filename: str) -> str:
    """Return a safe basename for a font upload.

    Keeps only the basename, drops control characters and path separators,
    retains unicode letters/digits plus ``-``/``_``/``.``, and caps the
    result at 120 characters. Falls back to ``"font"`` when the stem is empty.
    """
    base = os.path.basename(filename or "")
    cleaned = "".join(
        ch
        for ch in base
        if ch not in ("/", "\\")
        and unicodedata.category(ch)[0] != "C"
        and (ch.isalnum() or ch in "-_.")
    )
    cleaned = cleaned[: _MAX_FONT_FILENAME_LEN]
    if cleaned in (".", "..") or not os.path.splitext(cleaned)[0]:
        return "font"
    return cleaned


def register_font(font_path: Path) -> bool:
    """Copy ``font_path`` into ``~/.fonts`` and refresh the fontconfig cache.

    Best-effort: any failure (missing fc-cache, unwritable home, ...) is
    swallowed and reported as ``False``.
    """
    try:
        fonts_dir = Path.home() / ".fonts"
        fonts_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(font_path, fonts_dir / font_path.name)
        subprocess.run(["fc-cache", "-f"], timeout=10, capture_output=True)
    except Exception:
        log.exception("font registration failed for %s", font_path)
        return False
    return True


def sync_fonts(storage: Storage) -> int:
    """Register every font under the ``fonts/`` storage prefix with fontconfig.

    Each font is downloaded to a temp file and passed to :func:`register_font`;
    returns the count of successfully registered fonts. Failures are logged
    and skipped (best-effort).
    """
    registered = 0
    with tempfile.TemporaryDirectory(prefix="sfc-font-sync-") as tmpdir:
        for key in storage.list("fonts/"):
            try:
                local = storage.open_path(key)
                tmp_path = Path(tmpdir) / Path(key).name
                shutil.copyfile(local, tmp_path)
                if register_font(tmp_path):
                    registered += 1
            except Exception:
                log.exception("font sync failed for %s", key)
    return registered
