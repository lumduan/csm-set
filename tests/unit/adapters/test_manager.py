"""Unit tests for ``AdapterManager`` graceful-degradation behaviour."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from csm.adapters import AdapterManager, PostgresAdapter
from csm.config.settings import Settings


def _settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    db_write_enabled: bool,
    db_csm_set_dsn: str | None,
) -> Settings:
    """Build ``Settings`` with the relevant fields configured via env."""
    monkeypatch.setenv("CSM_DB_WRITE_ENABLED", str(db_write_enabled).lower())
    if db_csm_set_dsn is None:
        monkeypatch.delenv("CSM_DB_CSM_SET_DSN", raising=False)
    else:
        monkeypatch.setenv("CSM_DB_CSM_SET_DSN", db_csm_set_dsn)
    monkeypatch.delenv("CSM_DB_GATEWAY_DSN", raising=False)
    monkeypatch.delenv("CSM_MONGO_URI", raising=False)
    monkeypatch.setenv("TVKIT_AUTH_TOKEN", "")
    return Settings()


async def test_disabled_flag_yields_all_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _settings(monkeypatch, db_write_enabled=False, db_csm_set_dsn=None)
    manager = await AdapterManager.from_settings(s)

    assert manager.postgres is None
    assert manager.mongo is None
    assert manager.gateway is None


async def test_missing_dsn_logs_warning_and_postgres_none(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    s = _settings(monkeypatch, db_write_enabled=True, db_csm_set_dsn=None)
    with caplog.at_level(logging.WARNING, logger="csm.adapters"):
        manager = await AdapterManager.from_settings(s)

    assert manager.postgres is None
    assert any("db_csm_set_dsn is not set" in rec.message for rec in caplog.records)


async def test_connect_failure_logs_warning_and_postgres_none(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    s = _settings(
        monkeypatch,
        db_write_enabled=True,
        db_csm_set_dsn="postgresql://nope:nope@nowhere/db_csm_set",
    )

    async def _boom(self: PostgresAdapter) -> None:
        raise OSError("Connection refused")

    with (
        patch.object(PostgresAdapter, "connect", new=_boom),
        caplog.at_level(logging.WARNING, logger="csm.adapters"),
    ):
        manager = await AdapterManager.from_settings(s)

    assert manager.postgres is None
    assert any("PostgresAdapter connect failed" in rec.message for rec in caplog.records)


async def test_happy_path_initialises_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _settings(
        monkeypatch,
        db_write_enabled=True,
        db_csm_set_dsn="postgresql://u:p@h:5432/db_csm_set",
    )
    connect_calls: list[None] = []

    async def _ok(self: PostgresAdapter) -> None:
        connect_calls.append(None)

    with patch.object(PostgresAdapter, "connect", new=_ok):
        manager = await AdapterManager.from_settings(s)

    assert manager.postgres is not None
    assert isinstance(manager.postgres, PostgresAdapter)
    assert len(connect_calls) == 1


async def test_close_runs_when_postgres_set() -> None:
    fake = AsyncMock(spec=PostgresAdapter)
    manager = AdapterManager(postgres=fake)
    await manager.close()

    fake.close.assert_awaited_once()
    assert manager.postgres is None


async def test_close_swallows_close_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = AsyncMock(spec=PostgresAdapter)
    fake.close = AsyncMock(side_effect=RuntimeError("flaky teardown"))
    manager = AdapterManager(postgres=fake)

    with caplog.at_level(logging.WARNING, logger="csm.adapters"):
        await manager.close()

    assert manager.postgres is None
    assert any("PostgresAdapter close raised" in rec.message for rec in caplog.records)


async def test_close_without_postgres_is_noop() -> None:
    manager = AdapterManager()
    await manager.close()
    assert manager.postgres is None


async def test_ping_returns_empty_dict_when_no_adapter() -> None:
    manager = AdapterManager()
    assert await manager.ping() == {}


async def test_ping_reflects_postgres_status() -> None:
    fake = AsyncMock(spec=PostgresAdapter)
    fake.ping = AsyncMock(return_value=True)
    manager = AdapterManager(postgres=fake)

    assert await manager.ping() == {"postgres": "ok"}


async def test_ping_returns_error_when_postgres_ping_raises() -> None:
    fake = AsyncMock(spec=PostgresAdapter)
    fake.ping = AsyncMock(side_effect=OSError("boom"))
    manager = AdapterManager(postgres=fake)

    result = await manager.ping()

    assert result["postgres"].startswith("error:")
    assert "boom" in result["postgres"]


async def test_ping_error_when_select_returns_unexpected() -> None:
    fake = AsyncMock(spec=PostgresAdapter)
    fake.ping = AsyncMock(return_value=False)
    manager = AdapterManager(postgres=fake)

    assert await manager.ping() == {"postgres": "error:select_1_failed"}
