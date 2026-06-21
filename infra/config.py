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


settings = Settings()
