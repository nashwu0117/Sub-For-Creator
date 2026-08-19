"""Local-disk storage backend: plain files under a base directory."""

from __future__ import annotations

import os
import shutil

from .base import Storage, _resolve_path


class LocalStorage(Storage):
    """Stores each object as a file under ``base_dir`` (created on demand)."""

    def __init__(self, base_dir: str):
        self.base_dir = os.path.abspath(base_dir)

    def save(self, source: str | bytes, key: str) -> None:
        """Persist ``source`` (local path or bytes) at ``key``."""
        target = _resolve_path(self.base_dir, key)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if isinstance(source, bytes):
            with open(target, "wb") as fh:
                fh.write(source)
            return
        if os.path.abspath(source) == target:
            return  # already in place (writable_path + save round-trip)
        shutil.copyfile(source, target)

    def open_path(self, key: str) -> str:
        """The object's on-disk path (direct; nothing to download for local)."""
        return _resolve_path(self.base_dir, key)

    def writable_path(self, key: str) -> str:
        """On-disk path for writing, with parent directories created."""
        path = _resolve_path(self.base_dir, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def exists(self, key: str) -> bool:
        return os.path.isfile(_resolve_path(self.base_dir, key))

    def stat(self, key: str) -> tuple[int, float] | None:
        path = _resolve_path(self.base_dir, key)
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return None
        return (st.st_size, st.st_mtime)

    def list(self, prefix: str) -> list[str]:
        """Recursively list keys under ``prefix`` (prefix must end with ``/``)."""
        _resolve_path(self.base_dir, prefix)
        root = os.path.join(self.base_dir, prefix)
        if not os.path.isdir(root):
            return []
        keys: list[str] = []
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                full = os.path.join(dirpath, filename)
                rel = os.path.relpath(full, self.base_dir)
                keys.append(rel.replace(os.sep, "/"))
        return sorted(keys)

    def delete_dir(self, prefix: str) -> None:
        """Recursively delete everything under ``prefix`` (no-op if absent)."""
        path = _resolve_path(self.base_dir, prefix)
        shutil.rmtree(path, ignore_errors=True)
