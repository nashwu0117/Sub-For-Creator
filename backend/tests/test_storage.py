"""Unit tests for ``app.storage``: key validation, key helpers, LocalStorage
round-trip, and S3 key/path logic that needs no network."""

from __future__ import annotations

import pytest

from app.config import Settings, get_settings
from app.storage import (
    InvalidStorageKeyError,
    LocalStorage,
    S3Storage,
    Storage,
    audio_key,
    get_storage,
    render_key,
    source_key,
    validate_key,
)
from app.storage.base import _reset_storage

# ------------------------------------------------------------------ helpers


@pytest.fixture(autouse=True)
def _reset_storage_state(monkeypatch):
    """Drop the cached storage singleton and settings cache around each test."""
    get_settings.cache_clear()
    _reset_storage()
    yield
    get_settings.cache_clear()
    _reset_storage()


# ------------------------------------------------------------- key helpers


def test_source_key_format():
    assert source_key("abc123", "mp4") == "jobs/abc123/source.mp4"
    assert source_key("abc123", ".mp4") == "jobs/abc123/source.mp4"
    assert source_key("abc123", " .MP4 ") == "jobs/abc123/source.mp4"
    assert source_key("abc123", "bin") == "jobs/abc123/source.bin"


def test_audio_key_format():
    assert audio_key("abc123") == "jobs/abc123/audio.wav"


def test_render_key_format():
    assert render_key("abc123", "burned.mp4") == "jobs/abc123/burned.mp4"
    assert render_key("abc123", "alpha.webm") == "jobs/abc123/alpha.webm"


# ------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "bad",
    [
        "../evil",
        "a/../b",
        "jobs/../etc/passwd",
        "/absolute/path",
        "has space",
        "back\\slash",
        "bad\x00null",
        "",
    ],
)
def test_validate_key_rejects(bad):
    with pytest.raises(InvalidStorageKeyError):
        validate_key(bad)


@pytest.mark.parametrize("good", ["fonts/a.ttf", "jobs/abc/source.mp4", "a/b/c.d-e_f", "x"])
def test_validate_key_accepts(good):
    assert validate_key(good) == good


def test_helpers_reject_traversal():
    with pytest.raises(InvalidStorageKeyError):
        source_key("../x", ".mp4")
    with pytest.raises(InvalidStorageKeyError):
        render_key("a", "../escape.mp4")


def test_local_storage_rejects_traversal(tmp_path):
    storage = LocalStorage(str(tmp_path))
    with pytest.raises(InvalidStorageKeyError):
        storage.save(b"x", "../escape")
    with pytest.raises(InvalidStorageKeyError):
        storage.open_path("../../etc/passwd")
    with pytest.raises(InvalidStorageKeyError):
        storage.exists("/absolute")
    with pytest.raises(InvalidStorageKeyError):
        storage.list("../")


# ------------------------------------------------------- LocalStorage


def test_local_roundtrip_bytes(tmp_path):
    storage = LocalStorage(str(tmp_path / "base"))
    key = "jobs/deadbeef/source.mp4"
    storage.save(b"\x00\x01video", key)

    assert storage.exists(key)
    size, mtime = storage.stat(key)
    assert size == 7
    assert mtime > 0

    with open(storage.open_path(key), "rb") as fh:
        assert fh.read() == b"\x00\x01video"
    # on-disk layout mirrors the key hierarchy
    assert (tmp_path / "base" / "jobs" / "deadbeef" / "source.mp4").is_file()


def test_local_save_from_path(tmp_path):
    src = tmp_path / "src.wav"
    src.write_bytes(b"RIFFfake")
    storage = LocalStorage(str(tmp_path / "base"))

    storage.save(str(src), "jobs/x/audio.wav")
    with open(storage.open_path("jobs/x/audio.wav"), "rb") as fh:
        assert fh.read() == b"RIFFfake"


def test_local_writable_path_roundtrip(tmp_path):
    storage = LocalStorage(str(tmp_path / "base"))
    key = "jobs/x/burned.mp4"
    path = storage.writable_path(key)
    with open(path, "wb") as fh:
        fh.write(b"render")
    storage.save(path, key)  # same-file save must be a no-op, not a crash
    assert storage.exists(key)
    assert storage.stat(key)[0] == 6


def test_local_missing_key(tmp_path):
    storage = LocalStorage(str(tmp_path))
    assert not storage.exists("jobs/nope/source.mp4")
    assert storage.stat("jobs/nope/source.mp4") is None
    assert storage.list("fonts/") == []


def test_local_list_and_delete_dir(tmp_path):
    storage = LocalStorage(str(tmp_path / "base"))
    storage.save(b"a", "fonts/foo.ttf")
    storage.save(b"b", "fonts/sub/bar.otf")
    storage.save(b"c", "jobs/x/source.mp4")

    assert storage.list("fonts/") == ["fonts/foo.ttf", "fonts/sub/bar.otf"]

    storage.delete_dir("fonts/")
    assert storage.list("fonts/") == []
    assert storage.exists("fonts/foo.ttf") is False
    # unrelated prefix survives
    assert storage.exists("jobs/x/source.mp4")


# ----------------------------------------------------------- get_storage


def test_get_storage_returns_local(monkeypatch):
    monkeypatch.setenv("SFC_STORAGE_BACKEND", "local")
    _reset_storage()
    storage = get_storage()
    assert isinstance(storage, LocalStorage)
    assert isinstance(storage, Storage)


def test_get_storage_returns_s3(monkeypatch):
    monkeypatch.setenv("SFC_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("SFC_S3_BUCKET", "test-bucket")
    _reset_storage()
    storage = get_storage()
    assert isinstance(storage, S3Storage)
    assert isinstance(storage, Storage)
    assert storage.bucket == "test-bucket"


def test_get_storage_unknown_backend(monkeypatch):
    monkeypatch.setenv("SFC_STORAGE_BACKEND", "magic")
    _reset_storage()
    with pytest.raises(ValueError, match="storage_backend"):
        get_storage()


def test_get_storage_is_singleton():
    assert get_storage() is get_storage()


# ------------------------------------------------------------ S3Storage


def _dummy_settings(**overrides) -> Settings:
    kwargs = {
        "storage_backend": "s3",
        "s3_bucket": "test-bucket",
        "s3_endpoint_url": "http://localhost:9000",
        "s3_access_key": "ak",
        "s3_secret_key": "sk",
    }
    kwargs.update(overrides)
    return Settings(**kwargs)


def test_s3_constructor_with_dummy_settings(tmp_path):
    settings = _dummy_settings(upload_dir=str(tmp_path / "store"))
    storage = S3Storage(settings)
    assert storage.bucket == "test-bucket"
    assert storage._s3_client is None  # boto3 not touched at construction


def test_s3_cache_path_mapping(tmp_path):
    storage = S3Storage(_dummy_settings(upload_dir=str(tmp_path)))
    assert storage._cache_path("jobs/x/audio.wav") == str(
        tmp_path / ".cache" / "jobs" / "x" / "audio.wav"
    )


def test_s3_cache_path_rejects_traversal(tmp_path):
    storage = S3Storage(_dummy_settings(upload_dir=str(tmp_path)))
    with pytest.raises(InvalidStorageKeyError):
        storage._cache_path("../escape")


def test_s3_methods_validate_key_before_network(tmp_path):
    storage = S3Storage(_dummy_settings(upload_dir=str(tmp_path)))
    for method, args in (
        ("save", (b"x", "../escape")),
        ("open_path", ("../escape",)),
        ("writable_path", ("../escape",)),
        ("exists", ("../escape",)),
        ("stat", ("../escape",)),
        ("list", ("../",)),
        ("delete_dir", ("../",)),
    ):
        with pytest.raises(InvalidStorageKeyError):
            getattr(storage, method)(*args)


def test_s3_missing_bucket_raises_clear_error(tmp_path):
    storage = S3Storage(_dummy_settings(s3_bucket=None, upload_dir=str(tmp_path)))
    with pytest.raises(ValueError, match="s3_bucket"):
        storage.exists("jobs/x/source.mp4")
