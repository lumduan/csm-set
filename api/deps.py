"""Shared dependency providers for the FastAPI layer."""

from fastapi import Request

from api.jobs import JobRegistry
from csm.adapters import AdapterManager
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


def get_adapter_manager(request: Request) -> AdapterManager:
    """Return the shared :class:`AdapterManager` from application state.

    The manager is constructed in the FastAPI ``lifespan`` and lives on
    ``app.state.adapters``. Every adapter slot may be ``None`` when
    ``db_write_enabled`` is ``False`` or a DSN is missing — callers must
    null-check ``manager.postgres`` (etc.) before use.

    Raises:
        RuntimeError: If the manager has not been initialised (e.g. accessed
            before ``lifespan`` startup).
    """

    manager = getattr(request.app.state, "adapters", None)
    if manager is None:
        raise RuntimeError(
            "AdapterManager has not been initialised. It is built during FastAPI lifespan startup."
        )
    return manager  # type: ignore[no-any-return]


__all__: list[str] = [
    "get_adapter_manager",
    "get_jobs",
    "get_settings",
    "get_store",
    "set_store",
]
