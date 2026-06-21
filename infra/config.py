"""Process configuration, loaded from environment / .env.

Most settings use the ALPHA_ prefix; a few honor external conventions
(ANTHROPIC_API_KEY, STORAGE_EMULATOR_HOST, REDIS_URL) via explicit aliases.
"""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ALPHA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Redis (state + event bus + queue + budget)
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("ALPHA_REDIS_URL", "REDIS_URL"),
    )

    # Dispatch
    dispatch_backend: str = "local"  # "local" | "modal"
    max_depth: int = 1
    max_fanout: int = 3
    default_budget: int = 100
    dispatch_cost: int = 1  # budget units charged per dispatch

    # Agent
    model: str = "claude-sonnet-4-6"
    max_turns: int = 40

    # API / CORS — browser origins allowed to call the API (override via env JSON)
    cors_allow_origins: list[str] = ["http://localhost:3000"]

    # Artifacts
    gcs_bucket: str | None = None
    artifacts_dir: str = ".artifacts"
    storage_emulator_host: str | None = Field(
        default=None, validation_alias=AliasChoices("STORAGE_EMULATOR_HOST")
    )

    # Credentials
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "ALPHA_ANTHROPIC_API_KEY"),
    )
    # GCS service-account key for Modal containers. Prefer base64 (single-line; the raw
    # multi-line JSON hangs `modal secret create` on the command line). JSON kept as a
    # fallback for other injection paths.
    google_credentials_b64: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GOOGLE_APPLICATION_CREDENTIALS_B64", "ALPHA_GOOGLE_CREDENTIALS_B64"
        ),
    )
    google_credentials_json: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GOOGLE_APPLICATION_CREDENTIALS_JSON", "ALPHA_GOOGLE_CREDENTIALS_JSON"
        ),
    )
    # SA key file path for local runs (read from .env, which does NOT export to os.environ,
    # so storage.Client() can't auto-discover it — we pass it explicitly).
    google_credentials_file: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GOOGLE_APPLICATION_CREDENTIALS", "ALPHA_GOOGLE_CREDENTIALS_FILE"
        ),
    )


settings = Settings()
