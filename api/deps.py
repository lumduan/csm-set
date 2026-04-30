"""Shared dependency providers for the FastAPI layer."""

from fastapi import Request

from api.jobs import JobRegistry
from csm.config.settings import Settings, settings
from csm.data.store import ParquetStore

_STORE: ParquetStore | None = None


def set_store(store: ParquetStore) -> None:
    """Register the shared parquet store instance for API handlers."""

    global _STORE
    _STORE = store


def get_settings() -> Settings:
    """Return the module-level application settings singleton."""

    return settings


def get_store() -> ParquetStore:
    """Return the shared parquet store instance.

    Raises:
        RuntimeError: If the store has not been initialised.
    """

    if _STORE is None:
        raise RuntimeError("ParquetStore has not been initialised.")
    return _STORE


def get_jobs(request: Request) -> JobRegistry:
    """Return the shared JobRegistry instance from application state."""

    return request.app.state.jobs  # type: ignore[no-any-return]


__all__: list[str] = ["get_jobs", "get_settings", "get_store", "set_store"]
