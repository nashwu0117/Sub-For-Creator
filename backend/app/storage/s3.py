"""S3-compatible object storage backend (boto3, imported lazily).

Objects live in a bucket; reads/writes through ffmpeg/subprocess/FileResponse
go via a local cache directory (``<upload_dir>/.cache``) that is downloaded
on demand and keyed by storage key. The cache lives outside any job's own
directory so TTL cleanup never fights it.
"""

from __future__ import annotations

import os
from datetime import timezone

from app.config import Settings

from .base import Storage, _resolve_path, validate_key

#: delete_objects accepts at most 1000 keys per request
_DELETE_BATCH = 1000


class S3Storage(Storage):
    """Stores objects in an S3-compatible bucket with a local read cache."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._s3_client: object | None = None
        self.bucket = settings.s3_bucket or ""
        self._cache_dir = os.path.join(settings.upload_dir, ".cache")

    # ------------------------------------------------------------- helpers

    def _client(self):  # noqa: ANN202
        """Lazily create (and cache) the boto3 S3 client from settings."""
        if self._s3_client is None:
            import boto3  # lazy: keeps the CLI-only path free of the AWS SDK

            s = self._settings
            kwargs: dict = {}
            if s.s3_endpoint_url:
                kwargs["endpoint_url"] = s.s3_endpoint_url
            if s.s3_access_key:
                kwargs["aws_access_key_id"] = s.s3_access_key
            if s.s3_secret_key:
                kwargs["aws_secret_access_key"] = s.s3_secret_key
            self._s3_client = boto3.client("s3", **kwargs)
        return self._s3_client

    def _require_bucket(self) -> str:
        if not self.bucket:
            raise ValueError("s3_bucket is not configured")
        return self.bucket

    def _cache_path(self, key: str) -> str:
        """Local cache path for ``key`` (mirrors the key hierarchy)."""
        path = _resolve_path(self._cache_dir, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    @staticmethod
    def _is_404(exc: object) -> bool:
        """True when a botocore ClientError is a plain missing-object 404."""
        resp = getattr(exc, "response", None) or {}
        return resp.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404

    # ------------------------------------------------------------- Storage

    def save(self, source: str | bytes, key: str) -> None:
        validate_key(key)
        bucket = self._require_bucket()
        client = self._client()
        if isinstance(source, bytes):
            client.put_object(Bucket=bucket, Key=key, Body=source)
        else:
            client.upload_file(source, bucket, key)

    def open_path(self, key: str) -> str:
        """Local cache path, downloading from S3 first when not cached."""
        local = self._cache_path(key)
        if not os.path.exists(local):
            self._client().download_file(self._require_bucket(), key, local)
        return local

    def writable_path(self, key: str) -> str:
        """Local cache path ready for writing (downloaded on the next ``save``)."""
        return self._cache_path(key)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        validate_key(key)
        try:
            self._client().head_object(Bucket=self._require_bucket(), Key=key)
            return True
        except ClientError as exc:
            if self._is_404(exc):
                return False
            raise

    def stat(self, key: str) -> tuple[int, float] | None:
        from botocore.exceptions import ClientError

        validate_key(key)
        try:
            resp = self._client().head_object(Bucket=self._require_bucket(), Key=key)
        except ClientError as exc:
            if self._is_404(exc):
                return None
            raise
        size = int(resp["ContentLength"])
        mtime = resp["LastModified"]
        if mtime.tzinfo is None:
            mtime = mtime.replace(tzinfo=timezone.utc)
        return (size, mtime.timestamp())

    def list(self, prefix: str) -> list[str]:
        validate_key(prefix)
        bucket = self._require_bucket()
        client = self._client()
        paginator = client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return sorted(keys)

    def delete_dir(self, prefix: str) -> None:
        validate_key(prefix)
        bucket = self._require_bucket()
        client = self._client()
        keys = self.list(prefix)
        for i in range(0, len(keys), _DELETE_BATCH):
            batch = keys[i : i + _DELETE_BATCH]
            client.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
            )
