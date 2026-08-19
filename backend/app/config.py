"""Application settings — pydantic-settings, env prefix ``SFC_``.

All runtime knobs live here; the API layer reads them via ``get_settings()``
(cached singleton). Tests override values through ``SFC_*`` env vars and
``reset_settings()``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

#: Whisper-supported languages surfaced by ``GET /api/config``.
SUPPORTED_LANGUAGES: list[str] = [
    "zh",
    "en",
    "ja",
    "ko",
    "yue",
    "de",
    "es",
    "fr",
    "it",
    "pt",
    "ru",
    "th",
    "vi",
    "ar",
    "hi",
    "nl",
    "pl",
    "tr",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SFC_", env_file=".env", extra="ignore")

    # --- storage / db ---
    database_url: str = "sqlite:///./data/app.db"
    upload_dir: str = "./storage"
    storage_backend: str = "local"  # "local" | "s3"
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    # --- limits (see docs/API.md limits table) ---
    max_upload_mb: float = 1024
    max_duration_min: float = 60
    daily_seconds_per_session: int = 3600
    max_queue: int = 50
    #: worker-side concurrency only; the API enforces queue length via max_queue
    max_concurrent: int = 2
    ttl_hours: float = 48
    upload_rate_limit: int = 5  # uploads per 60s sliding window per session token
    #: per-font upload cap for custom fonts (see docs/API.md limits table)
    max_font_mb: int = 20

    # --- queue ---
    queue_backend: str = "celery"  # "celery" | "inline"
    celery_broker_url: str = "redis://localhost:6379/0"

    # --- transcription / rendering ---
    whisper_model: str = "large-v3"
    max_line_chars: int = 16
    render_timeout_seconds: int = 300

    # --- misc ---
    #: env accepts comma-separated list or JSON array (see _split_cors_origins)
    cors_origins: Annotated[list[str], NoDecode] = ["*"]
    version: str = "0.1.0"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return ["*"]
            if v.startswith("["):
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return parsed
                except json.JSONDecodeError:
                    pass
            return [item.strip() for item in v.split(",") if item.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton; call ``reset_settings()`` to re-read env."""
    return Settings()


def reset_settings() -> None:
    """Drop the cached settings so the next ``get_settings()`` re-reads env."""
    get_settings.cache_clear()
