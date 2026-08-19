"""Storage abstraction: local disk and S3-compatible backends.

Public API: :class:`Storage` (backend interface), :class:`LocalStorage`,
:class:`S3Storage`, :func:`get_storage` (settings-driven cached singleton) and
the ``source_key`` / ``audio_key`` / ``render_key`` key helpers used across
the API and worker layers.
"""

from .base import (
    InvalidStorageKeyError,
    Storage,
    audio_key,
    get_storage,
    render_key,
    source_key,
    validate_key,
)
from .local import LocalStorage
from .s3 import S3Storage

__all__ = [
    "InvalidStorageKeyError",
    "LocalStorage",
    "S3Storage",
    "Storage",
    "audio_key",
    "get_storage",
    "render_key",
    "source_key",
    "validate_key",
]
