"""Application settings for csm-set."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables.

    Attributes:
        env: Application environment name.
        data_dir: Directory containing raw and processed market data.
        log_level: Logging verbosity for application services.
        public_mode: When true, disable all live data fetch and write operations.
        results_dir: Directory containing pre-computed public outputs.
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
    )

    env: str = Field(default="development", description="Application environment name.")
    data_dir: Path = Field(default=Path("./data"), description="Base market data directory.")
    log_level: str = Field(default="INFO", description="Application log level.")
    public_mode: bool = Field(
        default=True,
        description="Disable live data fetches and write paths when enabled.",
    )
    results_dir: Path = Field(
        default=Path("./results"),
        description="Directory containing pre-computed results committed to git.",
    )
    api_host: str = Field(default="0.0.0.0", description="API bind host.")
    api_port: int = Field(default=8000, description="API bind port.")
    ui_port: int = Field(default=8080, description="NiceGUI bind port.")
    refresh_cron: str = Field(
        default="0 18 * * 1-5",
        description="Cron schedule for owner-side refresh jobs.",
    )
    tvkit_browser: str | None = Field(
        default=None,
        description="Optional browser profile name for tvkit authentication.",
    )
    tvkit_auth_token: str | None = Field(
        default=None,
        description="Optional TradingView authentication token.",
    )


settings: Settings = Settings()

__all__: list[str] = ["Settings", "settings"]
