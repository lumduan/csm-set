"""Application settings for csm-set."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
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
    refresh_held_max_attempts: int = Field(
        default=4,
        ge=1,
        description=(
            "Total outer-loop attempts for the held-symbols batch in daily_refresh "
            "(1 initial + N-1 retries). Held symbols are critical for NAV "
            "reconstruction, so this defaults higher than the universe sweep."
        ),
    )
    refresh_universe_max_attempts: int = Field(
        default=3,
        ge=1,
        description=(
            "Total outer-loop attempts for the universe sweep in daily_refresh "
            "(1 initial + N-1 retries)."
        ),
    )
    refresh_retry_delay_secs: int = Field(
        default=60,
        ge=0,
        description=(
            "Base backoff (seconds) between outer-loop retries in daily_refresh. "
            "Each subsequent retry doubles the wait (60s → 120s → 240s) with "
            "±20% jitter to let TradingView's connection pool recover."
        ),
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
        description=(
            "PostgreSQL DSN for the db_gateway database. Used by the read-only "
            "GatewayAdapter methods (read_daily_performance, read_portfolio_snapshots). "
            "The write-side path now goes through gateway_base_url / gateway_api_key; "
            "this DSN is retained only for history-read code paths."
        ),
    )
    gateway_base_url: str | None = Field(
        default=None,
        description=(
            "Base URL of the API Gateway used for write-back via the standard "
            "ingestion contract POST /api/v1/ingest/daily-report. "
            "Required for live write-back; absent means the HTTP write path is "
            "disabled and no daily report is posted. Example: "
            "http://quant-api-gateway:8000."
        ),
    )
    gateway_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "Shared INTERNAL_API_KEY presented as the X-API-Key header when "
            "posting daily reports to the gateway. Required when "
            "gateway_base_url is set."
        ),
    )
    mongo_uri: str | None = Field(
        default=None,
        description="MongoDB connection URI for the csm_logs database.",
    )
    db_write_enabled: bool = Field(
        default=False,
        description="Enable DB write-back after pipeline events when True.",
    )
    benchmark_symbol: str = Field(
        default="^SET.BK",
        description=(
            "Buy-and-hold benchmark symbol used by the per-strategy report's "
            "benchmark_equity_curve and benchmark_comparison sections. The column "
            "of this name must be present in the local prices store; if absent, "
            "the report is emitted without benchmark fields."
        ),
    )
    report_enable_public: bool = Field(
        default=True,
        description=(
            "When True (default), include the per-strategy report payload in the "
            "public results/static/ export. Owner mode only — public mode is "
            "read-only and never builds the report at runtime."
        ),
    )
    ohlcv_source: str = Field(
        default="db",
        description=(
            "OHLCV acquisition source for the owner-side daily refresh. "
            "'db' (default) — read pre-fetched bars from the Market Data Engine "
            "read API instead of touching tvkit (no tvkit cookie required in "
            "csm-set). 'parquet' — fetch from tvkit and persist the local Parquet "
            "store (DEPRECATED legacy path; kept for rollback). See "
            "feature-market-data-engine Phase 5."
        ),
    )
    market_data_engine_base_url: str | None = Field(
        default=None,
        description=(
            "Base URL of the Market Data Engine read API, used when "
            "ohlcv_source='db'. Inside quant-network use the service hostname, "
            "e.g. http://quant-marketdata-engine:8000; for host-local dev use "
            "http://localhost:8300. Required when ohlcv_source='db'; ignored "
            "otherwise."
        ),
    )
    market_data_engine_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "Shared secret presented as the X-API-Key header to the Market Data "
            "Engine read API. Optional — the engine only enforces it when its own "
            "MARKETDATA_ENGINE_API_KEY is set. Never logged."
        ),
    )

    @field_validator("ohlcv_source")
    @classmethod
    def _validate_ohlcv_source(cls, value: str) -> str:
        allowed: set[str] = {"parquet", "db"}
        if value not in allowed:
            raise ValueError(f"ohlcv_source must be one of {sorted(allowed)!r}, got {value!r}")
        return value

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

    @model_validator(mode="after")
    def _require_engine_url_for_db_source(self) -> Self:
        """Fail fast if ``ohlcv_source='db'`` without a Market Data Engine URL."""
        if self.ohlcv_source == "db" and not self.market_data_engine_base_url:
            raise ValueError(
                "CSM_MARKET_DATA_ENGINE_BASE_URL is required when CSM_OHLCV_SOURCE='db' "
                "(e.g. http://quant-marketdata-engine:8000 in-cluster or "
                "http://localhost:8300 for host-local dev)."
            )
        return self

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
