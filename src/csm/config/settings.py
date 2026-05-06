"""Application settings for csm-set."""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingViewCookies(BaseModel):
    """Parsed TradingView session cookies for authenticated tvkit access.

    The pre-extracted cookie dict is forwarded to ``tvkit.api.chart.OHLCV(cookies=...)``,
    bypassing tvkit's own ``TVKIT_AUTH_TOKEN`` env-var fallback (which expects a
    single JWT string, not a cookie dict). ``sessionid`` is required by tvkit's
    ``CookieProvider``; the remaining cookies are commonly emitted by TradingView
    and forwarded as-is.

    Attributes:
        sessionid: TradingView session identifier cookie. Required.
        sessionid_sign: Signed companion to ``sessionid``.
        device_t: TradingView device-tracking cookie.
        tv_ecuid: TradingView end-client UID cookie.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    sessionid: str = Field(min_length=1, description="TradingView sessionid cookie.")
    sessionid_sign: str | None = Field(
        default=None, description="TradingView sessionid_sign cookie."
    )
    device_t: str | None = Field(default=None, description="TradingView device_t cookie.")
    tv_ecuid: str | None = Field(default=None, description="TradingView tv_ecuid cookie.")

    def as_cookie_dict(self) -> dict[str, str]:
        """Return a flat ``name → value`` dict suitable for ``OHLCV(cookies=...)``."""
        return {k: v for k, v in self.model_dump().items() if v is not None}


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables.

    Attributes:
        env: Application environment name.
        data_dir: Directory containing raw and processed market data.
        log_level: Logging verbosity for application services.
        public_mode: When true, disable all live data fetch and write operations.
        results_dir: Directory containing pre-computed public outputs.
        tvkit_concurrency: Max concurrent tvkit fetch requests.
        tvkit_retry_attempts: Retry count for transient tvkit errors.
        api_host: API bind host.
        api_port: API bind port.
        api_key: Shared secret for ``X-API-Key`` auth on private-mode protected endpoints.
        ui_port: NiceGUI port.
        refresh_cron: Cron expression for owner-side refresh jobs.
        tvkit_auth_token: Parsed TradingView session cookies, or ``None`` for anonymous mode.
            Read from the ``TVKIT_AUTH_TOKEN`` env var (no ``CSM_`` prefix — the unprefixed
            name is used so the variable can be shared between csm-set and any other
            tooling that reads the same cookie blob). Value must be a JSON object
            containing at minimum a ``sessionid`` field.
    """

    model_config = SettingsConfigDict(
        env_prefix="CSM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    env: str = Field(default="development", description="Application environment name.")
    data_dir: Path = Field(default=Path("./data"), description="Base market data directory.")
    log_level: str = Field(default="INFO", description="Application log level.")
    public_mode: bool = Field(
        default=False,
        description="Disable live data fetches and write paths when enabled.",
    )
    results_dir: Path = Field(
        default=Path("./results"),
        description="Directory containing pre-computed results committed to git.",
    )
    tvkit_concurrency: int = Field(
        default=5,
        gt=0,
        description="Semaphore limit for concurrent tvkit fetch calls.",
    )
    tvkit_retry_attempts: int = Field(
        default=3,
        ge=0,
        description="Number of retries for transient tvkit network failures.",
    )
    api_host: str = Field(default="0.0.0.0", description="API bind host.")
    api_port: int = Field(default=8000, description="API bind port.")
    api_key: SecretStr | None = Field(
        default=None,
        description=(
            "Shared secret enforced via the X-API-Key header on private-mode protected "
            "endpoints. None disables auth (dev-only); production deployments must set "
            "CSM_API_KEY to a strong random value."
        ),
    )
    ui_port: int = Field(default=8080, description="NiceGUI bind port.")
    refresh_cron: str = Field(
        default="0 18 * * 1-5",
        description="Cron schedule for owner-side refresh jobs.",
    )
    tvkit_adjustment: str = Field(
        default="dividends",
        description=(
            "Price adjustment mode for OHLCV fetches. "
            "'dividends' — total-return backward adjustment (recommended for backtesting). "
            "'splits' — split-adjusted only (legacy pre-v0.11.0 behaviour)."
        ),
    )
    tvkit_auth_token: str | None = Field(
        default=None,
        validation_alias="TVKIT_AUTH_TOKEN",
        description=(
            "Raw JSON blob of TradingView session cookies. Read from the unprefixed "
            "TVKIT_AUTH_TOKEN env var (no CSM_ prefix). Use ``tvkit_cookies`` to "
            "access the parsed/validated form."
        ),
    )
    cors_allow_origins: str = Field(
        default="*",
        description="Comma-separated list of allowed CORS origins.",
    )
    db_csm_set_dsn: str | None = Field(
        default=None,
        description="PostgreSQL DSN for the db_csm_set database (strategy-private persistence).",
    )
    db_gateway_dsn: str | None = Field(
        default=None,
        description="PostgreSQL DSN for the db_gateway database (cross-strategy aggregation).",
    )
    mongo_uri: str | None = Field(
        default=None,
        description="MongoDB connection URI for the csm_logs database.",
    )
    db_write_enabled: bool = Field(
        default=False,
        description="Enable DB write-back after pipeline events when True.",
    )

    @field_validator("tvkit_adjustment")
    @classmethod
    def _validate_adjustment(cls, value: str) -> str:
        allowed: set[str] = {"splits", "dividends"}
        if value not in allowed:
            raise ValueError(f"tvkit_adjustment must be one of {sorted(allowed)!r}, got {value!r}")
        return value

    @field_validator("tvkit_auth_token", mode="before")
    @classmethod
    def _normalise_auth_token(cls, value: object) -> object:
        """Coerce empty/whitespace strings to ``None`` so anonymous mode is the default."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("tvkit_auth_token")
    @classmethod
    def _validate_auth_token_json(cls, value: str | None) -> str | None:
        """Fail fast at startup if TVKIT_AUTH_TOKEN is set but not parseable JSON.

        We validate the JSON shape here (without storing the parsed object) so
        misconfiguration surfaces during ``Settings()`` construction rather than
        at first fetch.
        """
        if value is None:
            return None
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "TVKIT_AUTH_TOKEN must be a JSON object containing TradingView "
                f"session cookies (e.g. {{'sessionid': '...'}}); got invalid JSON: {exc}"
            ) from exc
        # Run full structural validation now — discard the model, keep the raw string.
        TradingViewCookies.model_validate(payload)
        return value

    @property
    def tvkit_cookies(self) -> TradingViewCookies | None:
        """Return the parsed TradingView cookie blob, or ``None`` for anonymous mode.

        Parsing runs once per call (the JSON is small). The result is suitable for
        passing to ``tvkit.api.chart.OHLCV(cookies=...)`` via ``as_cookie_dict()``.
        """
        if self.tvkit_auth_token is None:
            return None
        return TradingViewCookies.model_validate(json.loads(self.tvkit_auth_token))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()


settings: Settings = get_settings()

__all__: list[str] = ["Settings", "TradingViewCookies", "get_settings", "settings"]
