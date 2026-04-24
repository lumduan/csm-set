"""Application settings for csm-set."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
        ui_port: NiceGUI port.
        refresh_cron: Cron expression for owner-side refresh jobs.
        tvkit_browser: Optional browser profile name for tvkit authentication.
        tvkit_auth_token: Optional TradingView authentication token.
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
    tvkit_browser: str | None = Field(
        default=None,
        description="Optional browser profile name for tvkit authentication.",
    )
    tvkit_auth_token: str | None = Field(
        default=None,
        description="Optional TradingView authentication token.",
    )

    @field_validator("tvkit_adjustment")
    @classmethod
    def _validate_adjustment(cls, value: str) -> str:
        allowed: set[str] = {"splits", "dividends"}
        if value not in allowed:
            raise ValueError(
                f"tvkit_adjustment must be one of {sorted(allowed)!r}, got {value!r}"
            )
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()


settings: Settings = get_settings()

__all__: list[str] = ["Settings", "get_settings", "settings"]
