"""Bundled, freely-licensed fonts available out of the box.

Files live in ``backend/fonts/`` (repo) and are copied to ``/app/fonts/`` in
the Docker image. Noto Sans/Serif CJK come from the Debian ``fonts-noto-cjk``
package; the Dockerfile symlinks their ``.ttc`` files into ``/app/fonts`` so
every entry here is served from a single directory. libass resolves the
``family`` names via fontconfig (fonts are also installed under
``/usr/share/fonts``), so choosing one of these families in the editor burns
the matching font into MP4/WebM exports without any upload.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Directory holding the bundled font files (repo ``backend/fonts/``, image ``/app/fonts/``).
FONTS_DIR = Path(os.environ.get("SFC_FONTS_DIR", Path(__file__).resolve().parents[2] / "fonts"))

#: Metadata for every bundled font. ``filename`` must exist in ``FONTS_DIR``;
#: ``family`` must match the fontconfig family name used by libass/ffmpeg.
SYSTEM_FONTS: list[dict] = [
    {
        "name": "Noto Sans CJK TC",
        "family": "Noto Sans CJK TC",
        "filename": "NotoSansCJK-Regular.ttc",
        "license": "SIL Open Font License 1.1",
        "license_url": "https://openfontlicense.org",
    },
    {
        "name": "Noto Sans CJK SC",
        "family": "Noto Sans CJK SC",
        "filename": "NotoSansCJK-Regular.ttc",
        "license": "SIL Open Font License 1.1",
        "license_url": "https://openfontlicense.org",
    },
    {
        "name": "Noto Serif CJK TC",
        "family": "Noto Serif CJK TC",
        "filename": "NotoSerifCJK-Regular.ttc",
        "license": "SIL Open Font License 1.1",
        "license_url": "https://openfontlicense.org",
    },
    {
        "name": "Noto Serif CJK SC",
        "family": "Noto Serif CJK SC",
        "filename": "NotoSerifCJK-Regular.ttc",
        "license": "SIL Open Font License 1.1",
        "license_url": "https://openfontlicense.org",
    },
    {
        "name": "LXGW WenKai",
        "family": "LXGW WenKai",
        "filename": "LXGWWenKai-Regular.ttf",
        "license": "SIL Open Font License 1.1",
        "license_url": "https://github.com/lxgw/LxgwWenKai",
    },
    {
        "name": "ZCOOL KuaiLe",
        "family": "ZCOOL KuaiLe",
        "filename": "ZCOOLKuaiLe-Regular.ttf",
        "license": "SIL Open Font License 1.1",
        "license_url": "https://github.com/google/fonts/tree/main/ofl/zcoolkuaile",
    },
    {
        "name": "ZCOOL XiaoWei",
        "family": "ZCOOL XiaoWei",
        "filename": "ZCOOLXiaoWei-Regular.ttf",
        "license": "SIL Open Font License 1.1",
        "license_url": "https://github.com/google/fonts/tree/main/ofl/zcoolxiaowei",
    },
]


def system_fonts() -> list[dict]:
    """SYSTEM_FONTS with runtime ``size`` (bytes) and ``available`` flags."""
    result: list[dict] = []
    for entry in SYSTEM_FONTS:
        path = FONTS_DIR / entry["filename"]
        try:
            size = path.stat().st_size if path.is_file() else 0
        except OSError:
            size = 0
        result.append(
            {
                **entry,
                "size": size,
                "available": path.is_file(),
            }
        )
    return result


def resolve_system_font(filename: str) -> Path | None:
    """Local path for a bundled font filename; ``None`` if unknown/missing."""
    for entry in SYSTEM_FONTS:
        if entry["filename"] == filename:
            path = FONTS_DIR / filename
            return path if path.is_file() else None
    return None
