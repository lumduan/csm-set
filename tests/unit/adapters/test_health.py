"""Unit tests for check_db_connectivity with mocked clients."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from csm.adapters.health import check_db_connectivity
from csm.config.settings import Settings


def _settings_with_db(
    monkeypatch: pytest.MonkeyPatch,
    *,
    db_write_enabled: bool = True,
    db_csm_set_dsn: str | None = "postgresql://test:test@localhost:5432/db_csm_set",
    db_gateway_dsn: str | None = "postgresql://test:test@localhost:5432/db_gateway",
    mongo_uri: str | None = "mongodb://localhost:27017/",
) -> Settings:
    """Build a Settings instance with DB fields set via env."""
    monkeypatch.setenv("CSM_DB_WRITE_ENABLED", str(db_write_enabled).lower())
    if db_csm_set_dsn:
        monkeypatch.setenv("CSM_DB_CSM_SET_DSN", db_csm_set_dsn)
    else:
        monkeypatch.delenv("CSM_DB_CSM_SET_DSN", raising=False)
    monkeypatch.delenv("CSM_DB_GATEWAY_DSN", raising=False)
    if mongo_uri:
        monkeypatch.setenv("CSM_MONGO_URI", mongo_uri)
    else:
        monkeypatch.delenv("CSM_MONGO_URI", raising=False)
    # Ensure no real TVKIT_AUTH_TOKEN leaks from host env.
    monkeypatch.setenv("TVKIT_AUTH_TOKEN", "")
    return Settings()


async def test_returns_none_when_db_write_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """check_db_connectivity returns None when db_write_enabled=False."""
    s = _settings_with_db(monkeypatch, db_write_enabled=False)
    result = await check_db_connectivity(s)
    assert result is None


async def test_both_ok_when_clients_succeed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns ok for both when asyncpg and motor connections succeed."""
    s = _settings_with_db(monkeypatch)

    mock_conn = AsyncMock()
    mock_conn.close = AsyncMock()

    async def mock_connect(*args: object, **kwargs: object) -> AsyncMock:
        return mock_conn

    mock_client = MagicMock()
    mock_client.admin.command = AsyncMock()
    mock_client.close = MagicMock()

    mock_motor_client = MagicMock(return_value=mock_client)

    with (
        patch("asyncpg.connect", new=mock_connect),
        patch("motor.motor_asyncio.AsyncIOMotorClient", new=mock_motor_client),
    ):
        result = await check_db_connectivity(s)

    assert result == {"postgres": "ok", "mongo": "ok"}
    mock_conn.close.assert_awaited_once()
    mock_client.admin.command.assert_awaited_once_with("ping")
    mock_client.close.assert_called_once()


async def test_postgres_error_when_connect_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns error for postgres when asyncpg.connect raises."""
    s = _settings_with_db(monkeypatch)

    async def mock_connect_fail(*args: object, **kwargs: object) -> None:
        raise OSError("Connection refused")

    mock_client = MagicMock()
    mock_client.admin.command = AsyncMock()
    mock_client.close = MagicMock()
    mock_motor_client = MagicMock(return_value=mock_client)

    with (
        patch("asyncpg.connect", new=mock_connect_fail),
        patch("motor.motor_asyncio.AsyncIOMotorClient", new=mock_motor_client),
    ):
        result = await check_db_connectivity(s)

    assert result is not None
    assert result["postgres"].startswith("error:")
    assert "Connection refused" in result["postgres"]
    assert result["mongo"] == "ok"


async def test_mongo_error_when_ping_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns error for mongo when ping command raises."""
    s = _settings_with_db(monkeypatch)

    mock_conn = AsyncMock()
    mock_conn.close = AsyncMock()

    async def mock_connect(*args: object, **kwargs: object) -> AsyncMock:
        return mock_conn

    mock_client = MagicMock()
    mock_client.admin.command = AsyncMock(side_effect=OSError("Server not found"))
    mock_client.close = MagicMock()
    mock_motor_client = MagicMock(return_value=mock_client)

    with (
        patch("asyncpg.connect", new=mock_connect),
        patch("motor.motor_asyncio.AsyncIOMotorClient", new=mock_motor_client),
    ):
        result = await check_db_connectivity(s)

    assert result is not None
    assert result["postgres"] == "ok"
    assert result["mongo"].startswith("error:")
    assert "Server not found" in result["mongo"]


async def test_both_error_when_both_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns error for both when both clients fail."""
    s = _settings_with_db(monkeypatch)

    async def mock_connect_fail(*args: object, **kwargs: object) -> None:
        raise OSError("Connection refused")

    mock_client = MagicMock()
    mock_client.admin.command = AsyncMock(side_effect=OSError("Server timeout"))
    mock_client.close = MagicMock()
    mock_motor_client = MagicMock(return_value=mock_client)

    with (
        patch("asyncpg.connect", new=mock_connect_fail),
        patch("motor.motor_asyncio.AsyncIOMotorClient", new=mock_motor_client),
    ):
        result = await check_db_connectivity(s)

    assert result == {
        "postgres": "error:Connection refused",
        "mongo": "error:Server timeout",
    }


async def test_missing_dsn_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns descriptive error when DSN or URI is not configured."""
    s = _settings_with_db(monkeypatch, db_csm_set_dsn=None, mongo_uri=None)

    result = await check_db_connectivity(s)

    assert result == {
        "postgres": "error:db_csm_set_dsn not configured",
        "mongo": "error:mongo_uri not configured",
    }
