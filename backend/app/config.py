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

    # --- limits (0 = unlimited) ---
    #: 0 = no upload size cap
    max_upload_mb: float = 0
    #: 0 = no media duration cap
    max_duration_min: float = 0
    #: 0 = no daily per-session cap
    daily_seconds_per_session: int = 0
    #: 0 = no queue length cap
    max_queue: int = 0
    #: worker-side concurrency only; the API enforces queue length via max_queue
    max_concurrent: int = 2
    ttl_hours: float = 48
    #: uploads per 60s sliding window per session token; 0 = no cap
    upload_rate_limit: int = 0
    #: per-font upload cap for custom fonts; 0 = no cap
    max_font_mb: int = 0

    # --- queue ---
    queue_backend: str = "celery"  # "celery" | "inline"
    celery_broker_url: str = "redis://localhost:6379/0"
    #: queue names for the multi-queue topology (see celery_app.task_routes).
    #: Overriding these requires matching ``-Q`` flags on every worker command.
    default_queue: str = "celery"
    transcribe_queue: str = "transcribe"
    render_queue: str = "render"

    # --- multi-GPU ---
    #: 0-based GPU index this worker process is pinned to via
    #: ``CUDA_VISIBLE_DEVICES``; ``None`` (unset) leaves the env untouched so a
    #: single-GPU host sees every device as before.
    gpu_index: int | None = None

    # --- transcription / rendering ---
    whisper_model: str = "large-v3"
    max_line_chars: int = 16
    render_timeout_seconds: int = 3600

    # --- ASR accuracy tiers ---
    #: lite | standard | pro; presets live in app.core.asr.TIER_PRESETS.
    #: Invalid values are rejected by resolve_asr_config() with a clear error.
    tier: str = "standard"
    #: None = use the tier preset (5 for lite/standard, 10 for pro)
    beam_size: int | None = None
    #: None = use the tier preset (0 = deterministic decoding)
    temperature: float | None = None
    #: None = use the tier preset (True)
    vad_enabled: bool | None = None

    # --- monitoring ---
    #: expose GET /api/metrics (Prometheus text format); set false to hard-off
    metrics_enabled: bool = True

    # --- misc ---
    #: env accepts comma-separated list or JSON array (see _split_cors_origins)
    cors_origins: Annotated[list[str], NoDecode] = ["*"]
    version: str = "0.1.0"

    # --- optional accounts (v2) ---
    #: name of the HTTP-only auth cookie
    auth_cookie_name: str = "sfc_session"
    #: set the Secure flag on the auth cookie (enable behind HTTPS)
    auth_cookie_secure: bool = False
    #: HMAC-SHA256 secret signing the auth cookie; change in production
    auth_secret: str = "sfc-dev-secret-change-me"
    #: auth cookie lifetime in days
    auth_session_days: int = 30

    @field_validator("gpu_index", mode="before")
    @classmethod
    def _empty_gpu_index_to_none(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return None
        return v

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
