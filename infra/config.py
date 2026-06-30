"""Process configuration, loaded from environment / .env.

Most settings use the ALPHA_ prefix; a few honor external conventions
(ANTHROPIC_API_KEY, STORAGE_EMULATOR_HOST, REDIS_URL) via explicit aliases.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env against the repo root (this file is infra/config.py) so the working
# directory doesn't matter — launching from web/ or anywhere else loads the same .env
# instead of silently falling back to defaults. In prod (Cloud Run) config comes from
# injected env vars, which take precedence, and .env is absent from the image, so this
# path simply finds nothing and behavior is unchanged.
_ENV_FILE = str(Path(__file__).resolve().parent.parent / ".env")

# redis-py's from_url() only accepts these schemes; anything else raises deep inside a
# swallowed loop exception (leadership_loop) and the runner silently never leads. Validate
# at Settings load so a malformed ALPHA_REDIS_URL secret fails LOUDLY on boot instead.
_VALID_REDIS_SCHEMES = ("redis://", "rediss://", "unix://")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ALPHA_",
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Redis (state + event bus + queue + budget)
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("ALPHA_REDIS_URL", "REDIS_URL"),
    )

    @field_validator("redis_url")
    @classmethod
    def _require_redis_scheme(cls, v: str) -> str:
        # Strip surrounding whitespace (a stray newline/space before the scheme also
        # trips from_url) and reject anything without a valid scheme — e.g. a bare
        # host:port, or a pasted "ALPHA_REDIS_URL=redis://..." env line stored verbatim
        # as the secret value (a real incident: it buries the scheme mid-string).
        s = v.strip()
        if not s.startswith(_VALID_REDIS_SCHEMES):
            raise ValueError(
                "ALPHA_REDIS_URL must start with redis://, rediss://, or unix:// — got a "
                "value with no valid scheme at the front (bare host:port, or a verbatim "
                "'ALPHA_REDIS_URL=...' env line). Fix the secret/env value."
            )
        return s

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

    # ---- Runner internal API (agents -> runner HTTP push) --------------------
    # Bootstrap/dev fallback only. Production auth is the per-session ephemeral
    # token (store.mint_agent_token) injected per-execution at spawn — see SEV-4.
    internal_token: str = Field(
        default="dev-internal-token",
        validation_alias=AliasChoices("ALPHA_INTERNAL_TOKEN"),
    )
    internal_runner_url: str = Field(
        default="http://localhost:8080",
        validation_alias=AliasChoices("ALPHA_INTERNAL_RUNNER_URL"),
    )
    # When true, allow the shared internal_token as a fallback bearer on /internal/*.
    # Keep FALSE in production (per-session tokens only).
    internal_token_fallback: bool = False

    # ---- Modal (sub-agents) + per-session volume mount root ------------------
    modal_app_name: str = Field(
        default="alpharesearch",
        validation_alias=AliasChoices("ALPHA_MODAL_APP_NAME"),
    )
    volume_root: str = Field(
        default="/mnt/alpha-volumes",
        validation_alias=AliasChoices("ALPHA_VOLUME_ROOT"),
    )

    # ---- Cloud Run (main-agent job) ----------------------------------------
    gcp_project: str = Field(
        default="alpharesearch-500100",
        validation_alias=AliasChoices("ALPHA_GCP_PROJECT", "GCP_PROJECT"),
    )
    gcp_region: str = Field(
        default="us-central1",
        validation_alias=AliasChoices("ALPHA_GCP_REGION", "GCP_REGION"),
    )
    main_agent_job_name: str = Field(
        default="alpha-main-agent",
        validation_alias=AliasChoices("ALPHA_MAIN_AGENT_JOB_NAME"),
    )

    # ---- Runner lifecycle ---------------------------------------------------
    # FastAPI startup launches the runner loops when true. Tests set it false and
    # drive the loop bodies (_consume_*_once / _reconcile_once) directly.
    runner_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("ALPHA_RUNNER_ENABLED"),
    )
    # Local dev only: when true, the API plays a scripted research run per session
    # (runner/local_sim.py) instead of spawning Cloud Run / Modal — so the full web
    # app works locally with no cloud credentials. Keep FALSE in production.
    local_sim: bool = Field(
        default=False,
        validation_alias=AliasChoices("ALPHA_LOCAL_SIM"),
    )

    # ---- Auth (optional Clerk verification on the public API) ----------------
    # When clerk_jwks_url is set, public endpoints require a verified Clerk JWT
    # and derive user_id from its `sub`. Unset = open dev mode (caller-supplied id).
    clerk_jwks_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ALPHA_CLERK_JWKS_URL", "CLERK_JWKS_URL"),
    )
    clerk_issuer: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ALPHA_CLERK_ISSUER", "CLERK_ISSUER"),
    )
    clerk_audience: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ALPHA_CLERK_AUDIENCE", "CLERK_AUDIENCE"),
    )

    @model_validator(mode="after")
    def _auth_requires_issuer(self) -> "Settings":
        # Fail fast: verifying JWKS-signed tokens without an issuer check is unsafe.
        if self.clerk_jwks_url and not self.clerk_issuer:
            raise ValueError(
                "ALPHA_CLERK_ISSUER is required when ALPHA_CLERK_JWKS_URL is set"
            )
        return self


settings = Settings()
