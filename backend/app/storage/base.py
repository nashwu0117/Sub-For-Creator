"""Storage abstraction: key helpers, validation, and the shared singleton.

Public surface (re-exported from ``app.storage``): :class:`Storage` (the
backend interface), :func:`get_storage` (settings-driven singleton) and the
``source_key`` / ``audio_key`` / ``render_key`` key helpers used across the
API and worker layers.
"""

from __future__ import annotations

import os
import threading
from abc import ABC, abstractmethod

from app.config import get_settings

#: Characters allowed inside a storage key. Anything else (spaces, control
#: chars, backslashes, ``..`` segments, leading ``/``) is rejected so a key
#: can never escape the storage base directory.
_KEY_WHITELIST = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/-"
)


class InvalidStorageKeyError(ValueError):
    """Raised when a storage key fails path-traversal / character validation."""


def validate_key(key: str) -> str:
    """Validate ``key`` and return it unchanged.

    Rejects empty keys, absolute paths, ``..`` segments and any character
    outside the whitelist.
    """
    if not isinstance(key, str) or not key:
        raise InvalidStorageKeyError(f"invalid storage key {key!r}: empty")
    if key.startswith("/"):
        raise InvalidStorageKeyError(f"invalid storage key {key!r}: absolute path")
    if ".." in key.split("/"):
        raise InvalidStorageKeyError(f"invalid storage key {key!r}: path traversal")
    if not all(ch in _KEY_WHITELIST for ch in key):
        raise InvalidStorageKeyError(f"invalid storage key {key!r}: forbidden characters")
    return key


def _normalize_ext(ext: str) -> str:
    """Lowercase ``ext`` and guarantee a leading dot (e.g. ``mp4`` -> ``.mp4``)."""
    ext = ext.strip().lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    return ext


def source_key(job_id: str, ext: str) -> str:
    """Storage key for the uploaded source file of ``job_id``."""
    return validate_key(f"jobs/{job_id}/source{_normalize_ext(ext)}")


def audio_key(job_id: str) -> str:
    """Storage key for the extracted 16 kHz mono WAV of ``job_id``."""
    return validate_key(f"jobs/{job_id}/audio.wav")


def render_key(job_id: str, kind: str) -> str:
    """Storage key for a rendered export (e.g. ``burned.mp4``, ``alpha.webm``)."""
    return validate_key(f"jobs/{job_id}/{kind}")


class Storage(ABC):
    """Abstract storage backend: local disk or S3-compatible object store."""

    @abstractmethod
    def save(self, source: str | bytes, key: str) -> None:
        """Persist ``source`` (a local file path or raw bytes) at ``key``."""

    @abstractmethod
    def open_path(self, key: str) -> str:
        """Return a local path ffmpeg/subprocess/FileResponse can read."""

    @abstractmethod
    def writable_path(self, key: str) -> str:
        """Return a local path suitable for writing before ``save``."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """True when an object exists at ``key``."""

    @abstractmethod
    def stat(self, key: str) -> tuple[int, float] | None:
        """Return ``(size_bytes, mtime_epoch_seconds)`` or ``None`` if missing."""

    @abstractmethod
    def list(self, prefix: str) -> list[str]:
        """Return all keys under ``prefix`` (recursive, sorted)."""

    @abstractmethod
    def delete_dir(self, prefix: str) -> None:
        """Recursively delete everything under ``prefix``."""


_storage: Storage | None = None
_storage_lock = threading.Lock()


def get_storage() -> Storage:
    """Thread-safe cached storage singleton selected by ``settings.storage_backend``.

    ``"local"`` -> :class:`~app.storage.local.LocalStorage`,
    ``"s3"`` -> :class:`~app.storage.s3.S3Storage`; anything else raises
    ``ValueError``. Backends are imported lazily to keep the CLI-only path
    free of the AWS SDK.
    """
    global _storage
    with _storage_lock:
        if _storage is not None:
            return _storage
        settings = get_settings()
        backend = settings.storage_backend
        if backend == "local":
            from app.storage.local import LocalStorage

            _storage = LocalStorage(settings.upload_dir)
        elif backend == "s3":
            from app.storage.s3 import S3Storage

            _storage = S3Storage(settings)
        else:
            raise ValueError(f"unknown storage_backend {backend!r}")
        return _storage


def _reset_storage() -> None:
    """Drop the cached storage singleton (used by tests)."""
    global _storage
    with _storage_lock:
        _storage = None


def _resolve_path(base_dir: str, key: str) -> str:
    """Join ``key`` onto ``base_dir`` and verify the result stays inside it.

    Keys are validated first; the commonpath check is a belt-and-braces guard
    so no key can ever escape the base directory.
    """
    base = os.path.abspath(base_dir)
    path = os.path.abspath(os.path.join(base, validate_key(key)))
    if os.path.commonpath([base, path]) != base:
        raise InvalidStorageKeyError(f"invalid storage key {key!r}: escapes base dir")
    return path
