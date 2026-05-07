"""Unit tests for ``AdapterManager`` graceful-degradation behaviour."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from csm.adapters import AdapterManager, GatewayAdapter, MongoAdapter, PostgresAdapter
from csm.config.settings import Settings


def _settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    db_write_enabled: bool,
    db_csm_set_dsn: str | None,
    mongo_uri: str | None = None,
    db_gateway_dsn: str | None = None,
) -> Settings:
    """Build ``Settings`` with the relevant fields configured via env."""
    monkeypatch.setenv("CSM_DB_WRITE_ENABLED", str(db_write_enabled).lower())
    if db_csm_set_dsn is None:
        monkeypatch.delenv("CSM_DB_CSM_SET_DSN", raising=False)
    else:
        monkeypatch.setenv("CSM_DB_CSM_SET_DSN", db_csm_set_dsn)
    if mongo_uri is None:
        monkeypatch.delenv("CSM_MONGO_URI", raising=False)
    else:
        monkeypatch.setenv("CSM_MONGO_URI", mongo_uri)
    if db_gateway_dsn is None:
        monkeypatch.delenv("CSM_DB_GATEWAY_DSN", raising=False)
    else:
        monkeypatch.setenv("CSM_DB_GATEWAY_DSN", db_gateway_dsn)
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


# ---------------------------------------------------------------------------
# Mongo branch (Phase 3)
# ---------------------------------------------------------------------------


async def test_missing_mongo_uri_logs_warning_and_mongo_none(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    s = _settings(
        monkeypatch,
        db_write_enabled=True,
        db_csm_set_dsn=None,  # also missing — focuses warning capture on mongo
        mongo_uri=None,
    )
    with caplog.at_level(logging.WARNING, logger="csm.adapters"):
        manager = await AdapterManager.from_settings(s)

    assert manager.mongo is None
    assert any("mongo_uri is not set" in rec.message for rec in caplog.records)


async def test_mongo_connect_failure_logs_warning_and_mongo_none(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    s = _settings(
        monkeypatch,
        db_write_enabled=True,
        db_csm_set_dsn=None,
        mongo_uri="mongodb://nope:27017/",
    )

    async def _boom(self: MongoAdapter) -> None:
        raise OSError("Mongo unreachable")

    with (
        patch.object(MongoAdapter, "connect", new=_boom),
        caplog.at_level(logging.WARNING, logger="csm.adapters"),
    ):
        manager = await AdapterManager.from_settings(s)

    assert manager.mongo is None
    assert any("MongoAdapter connect failed" in rec.message for rec in caplog.records)


async def test_happy_path_initialises_mongo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _settings(
        monkeypatch,
        db_write_enabled=True,
        db_csm_set_dsn=None,
        mongo_uri="mongodb://u:p@h:27017/",
    )

    async def _ok(self: MongoAdapter) -> None:
        return None

    with patch.object(MongoAdapter, "connect", new=_ok):
        manager = await AdapterManager.from_settings(s)

    assert manager.mongo is not None
    assert isinstance(manager.mongo, MongoAdapter)


async def test_close_runs_when_mongo_set() -> None:
    fake = AsyncMock(spec=MongoAdapter)
    manager = AdapterManager(mongo=fake)
    await manager.close()

    fake.close.assert_awaited_once()
    assert manager.mongo is None


async def test_close_swallows_mongo_close_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = AsyncMock(spec=MongoAdapter)
    fake.close = AsyncMock(side_effect=RuntimeError("flaky teardown"))
    manager = AdapterManager(mongo=fake)

    with caplog.at_level(logging.WARNING, logger="csm.adapters"):
        await manager.close()

    assert manager.mongo is None
    assert any("MongoAdapter close raised" in rec.message for rec in caplog.records)


async def test_ping_reflects_mongo_status() -> None:
    fake = AsyncMock(spec=MongoAdapter)
    fake.ping = AsyncMock(return_value=True)
    manager = AdapterManager(mongo=fake)

    assert await manager.ping() == {"mongo": "ok"}


async def test_ping_returns_error_when_mongo_ping_raises() -> None:
    fake = AsyncMock(spec=MongoAdapter)
    fake.ping = AsyncMock(side_effect=OSError("mongo boom"))
    manager = AdapterManager(mongo=fake)

    result = await manager.ping()

    assert result["mongo"].startswith("error:")
    assert "mongo boom" in result["mongo"]


async def test_ping_mongo_error_when_command_returns_unexpected() -> None:
    fake = AsyncMock(spec=MongoAdapter)
    fake.ping = AsyncMock(return_value=False)
    manager = AdapterManager(mongo=fake)

    assert await manager.ping() == {"mongo": "error:ping_failed"}


async def test_ping_combines_postgres_and_mongo() -> None:
    fake_pg = AsyncMock(spec=PostgresAdapter)
    fake_pg.ping = AsyncMock(return_value=True)
    fake_mongo = AsyncMock(spec=MongoAdapter)
    fake_mongo.ping = AsyncMock(return_value=True)
    manager = AdapterManager(postgres=fake_pg, mongo=fake_mongo)

    assert await manager.ping() == {"postgres": "ok", "mongo": "ok"}


async def test_close_runs_both_adapters() -> None:
    fake_pg = AsyncMock(spec=PostgresAdapter)
    fake_mongo = AsyncMock(spec=MongoAdapter)
    manager = AdapterManager(postgres=fake_pg, mongo=fake_mongo)

    await manager.close()

    fake_pg.close.assert_awaited_once()
    fake_mongo.close.assert_awaited_once()
    assert manager.postgres is None
    assert manager.mongo is None


# ---------------------------------------------------------------------------
# Gateway branch (Phase 4)
# ---------------------------------------------------------------------------


async def test_missing_gateway_dsn_logs_warning_and_gateway_none(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    s = _settings(
        monkeypatch,
        db_write_enabled=True,
        db_csm_set_dsn=None,
        mongo_uri=None,
        db_gateway_dsn=None,
    )
    with caplog.at_level(logging.WARNING, logger="csm.adapters"):
        manager = await AdapterManager.from_settings(s)

    assert manager.gateway is None
    assert any("db_gateway_dsn is not set" in rec.message for rec in caplog.records)


async def test_gateway_connect_failure_logs_warning_and_gateway_none(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    s = _settings(
        monkeypatch,
        db_write_enabled=True,
        db_csm_set_dsn=None,
        mongo_uri=None,
        db_gateway_dsn="postgresql://nope:nope@nowhere/db_gateway",
    )

    async def _boom(self: GatewayAdapter) -> None:
        raise OSError("Gateway unreachable")

    with (
        patch.object(GatewayAdapter, "connect", new=_boom),
        caplog.at_level(logging.WARNING, logger="csm.adapters"),
    ):
        manager = await AdapterManager.from_settings(s)

    assert manager.gateway is None
    assert any("GatewayAdapter connect failed" in rec.message for rec in caplog.records)


async def test_happy_path_initialises_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _settings(
        monkeypatch,
        db_write_enabled=True,
        db_csm_set_dsn=None,
        mongo_uri=None,
        db_gateway_dsn="postgresql://u:p@h:5432/db_gateway",
    )

    async def _ok(self: GatewayAdapter) -> None:
        return None

    with patch.object(GatewayAdapter, "connect", new=_ok):
        manager = await AdapterManager.from_settings(s)

    assert manager.gateway is not None
    assert isinstance(manager.gateway, GatewayAdapter)


async def test_close_runs_when_gateway_set() -> None:
    fake = AsyncMock(spec=GatewayAdapter)
    manager = AdapterManager(gateway=fake)
    await manager.close()

    fake.close.assert_awaited_once()
    assert manager.gateway is None


async def test_close_swallows_gateway_close_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = AsyncMock(spec=GatewayAdapter)
    fake.close = AsyncMock(side_effect=RuntimeError("flaky teardown"))
    manager = AdapterManager(gateway=fake)

    with caplog.at_level(logging.WARNING, logger="csm.adapters"):
        await manager.close()

    assert manager.gateway is None
    assert any("GatewayAdapter close raised" in rec.message for rec in caplog.records)


async def test_ping_reflects_gateway_status() -> None:
    fake = AsyncMock(spec=GatewayAdapter)
    fake.ping = AsyncMock(return_value=True)
    manager = AdapterManager(gateway=fake)

    assert await manager.ping() == {"gateway": "ok"}


async def test_ping_returns_error_when_gateway_ping_raises() -> None:
    fake = AsyncMock(spec=GatewayAdapter)
    fake.ping = AsyncMock(side_effect=OSError("gateway boom"))
    manager = AdapterManager(gateway=fake)

    result = await manager.ping()

    assert result["gateway"].startswith("error:")
    assert "gateway boom" in result["gateway"]


async def test_ping_gateway_error_when_select_returns_unexpected() -> None:
    fake = AsyncMock(spec=GatewayAdapter)
    fake.ping = AsyncMock(return_value=False)
    manager = AdapterManager(gateway=fake)

    assert await manager.ping() == {"gateway": "error:ping_failed"}


async def test_ping_combines_all_three_adapters() -> None:
    fake_pg = AsyncMock(spec=PostgresAdapter)
    fake_pg.ping = AsyncMock(return_value=True)
    fake_mongo = AsyncMock(spec=MongoAdapter)
    fake_mongo.ping = AsyncMock(return_value=True)
    fake_gw = AsyncMock(spec=GatewayAdapter)
    fake_gw.ping = AsyncMock(return_value=True)
    manager = AdapterManager(postgres=fake_pg, mongo=fake_mongo, gateway=fake_gw)

    assert await manager.ping() == {"postgres": "ok", "mongo": "ok", "gateway": "ok"}


async def test_close_runs_all_three_adapters() -> None:
    fake_pg = AsyncMock(spec=PostgresAdapter)
    fake_mongo = AsyncMock(spec=MongoAdapter)
    fake_gw = AsyncMock(spec=GatewayAdapter)
    manager = AdapterManager(postgres=fake_pg, mongo=fake_mongo, gateway=fake_gw)

    await manager.close()

    fake_pg.close.assert_awaited_once()
    fake_mongo.close.assert_awaited_once()
    fake_gw.close.assert_awaited_once()
    assert manager.postgres is None
    assert manager.mongo is None
    assert manager.gateway is None
