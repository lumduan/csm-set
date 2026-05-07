"""Integration tests for Phase 6 — ``/api/v1/history/*`` endpoints.

The tests cover the full app-level wiring (router mount, APIKey gating,
public-mode visibility) but stub the adapter slots on ``app.state.adapters``
so they do not need a live ``quant-infra-db`` stack. The companion module
:mod:`tests.integration.adapters.test_history_api` exercises the same
endpoints against the real databases under the ``infra_db`` marker.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock

from api.security import API_KEY_HEADER
from fastapi.testclient import TestClient

from csm.adapters import AdapterManager
from csm.adapters.gateway import GatewayAdapter
from csm.adapters.models import (
    BacktestSummaryRow,
    DailyPerformanceRow,
    EquityPoint,
    PortfolioSnapshotRow,
    SignalSnapshotDoc,
    TradeRow,
)
from csm.adapters.mongo import MongoAdapter
from csm.adapters.postgres import PostgresAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _install_adapters(
    client: TestClient,
    *,
    postgres: PostgresAdapter | None = None,
    mongo: MongoAdapter | None = None,
    gateway: GatewayAdapter | None = None,
) -> None:
    """Replace ``app.state.adapters`` with a manager carrying the given slots."""

    client.app.state.adapters = AdapterManager(  # type: ignore[attr-defined]
        postgres=postgres,
        mongo=mongo,
        gateway=gateway,
    )


def _stub_postgres(**method_returns: object) -> PostgresAdapter:
    """Return an :class:`AsyncMock` shaped like :class:`PostgresAdapter`."""

    mock = AsyncMock(spec=PostgresAdapter)
    for name, value in method_returns.items():
        getattr(mock, name).return_value = value
    return cast(PostgresAdapter, mock)


def _stub_mongo(**method_returns: object) -> MongoAdapter:
    """Return an :class:`AsyncMock` shaped like :class:`MongoAdapter`."""

    mock = AsyncMock(spec=MongoAdapter)
    for name, value in method_returns.items():
        getattr(mock, name).return_value = value
    return cast(MongoAdapter, mock)


def _stub_gateway(**method_returns: object) -> GatewayAdapter:
    """Return an :class:`AsyncMock` shaped like :class:`GatewayAdapter`."""

    mock = AsyncMock(spec=GatewayAdapter)
    for name, value in method_returns.items():
        getattr(mock, name).return_value = value
    return cast(GatewayAdapter, mock)


_FIXED_TIME: datetime = datetime(2026, 5, 6, 0, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Public mode — guard returns 403 for all history paths
# ---------------------------------------------------------------------------


class TestPublicModeForbidden:
    """In public mode every history endpoint is denied with 403 by ``public_mode_guard``."""

    def test_equity_curve_public_mode_returns_403(self, public_client: TestClient) -> None:
        resp = public_client.get("/api/v1/history/equity-curve")
        assert resp.status_code == 403
        assert "public mode" in resp.json()["detail"].lower()

    def test_trades_public_mode_returns_403(self, public_client: TestClient) -> None:
        resp = public_client.get("/api/v1/history/trades")
        assert resp.status_code == 403

    def test_performance_public_mode_returns_403(self, public_client: TestClient) -> None:
        resp = public_client.get("/api/v1/history/performance")
        assert resp.status_code == 403

    def test_portfolio_snapshots_public_mode_returns_403(self, public_client: TestClient) -> None:
        resp = public_client.get("/api/v1/history/portfolio-snapshots")
        assert resp.status_code == 403

    def test_backtests_public_mode_returns_403(self, public_client: TestClient) -> None:
        resp = public_client.get("/api/v1/history/backtests")
        assert resp.status_code == 403

    def test_signals_public_mode_returns_403(self, public_client: TestClient) -> None:
        resp = public_client.get("/api/v1/history/signals?date=2026-05-06")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Auth — APIKeyMiddleware gates GETs under PROTECTED_PREFIXES
# ---------------------------------------------------------------------------


class TestAuthRequired:
    """GETs to ``/api/v1/history/*`` need ``X-API-Key`` in private mode."""

    def test_missing_key_returns_401(self, private_client_with_key: tuple[TestClient, str]) -> None:
        client, _ = private_client_with_key
        resp = client.get("/api/v1/history/equity-curve")
        assert resp.status_code == 401
        body = resp.json()
        assert "Missing" in body["detail"]
        assert body["detail"].endswith("X-API-Key header.")

    def test_invalid_key_returns_401(self, private_client_with_key: tuple[TestClient, str]) -> None:
        client, _ = private_client_with_key
        resp = client.get(
            "/api/v1/history/equity-curve",
            headers={API_KEY_HEADER: "wrong"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert "Invalid" in body["detail"]


# ---------------------------------------------------------------------------
# 503 — adapter slot is None (default test-fixture state, no DSNs)
# ---------------------------------------------------------------------------


class TestAdapterUnavailable:
    """When the relevant adapter slot is ``None`` the endpoint returns 503."""

    def test_equity_curve_503_when_postgres_none(
        self, private_client_with_key: tuple[TestClient, str]
    ) -> None:
        client, key = private_client_with_key
        _install_adapters(client)
        resp = client.get(
            "/api/v1/history/equity-curve",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 503
        assert "postgres" in resp.json()["detail"]

    def test_trades_503_when_postgres_none(
        self, private_client_with_key: tuple[TestClient, str]
    ) -> None:
        client, key = private_client_with_key
        _install_adapters(client)
        resp = client.get("/api/v1/history/trades", headers={API_KEY_HEADER: key})
        assert resp.status_code == 503
        assert "postgres" in resp.json()["detail"]

    def test_performance_503_when_gateway_none(
        self, private_client_with_key: tuple[TestClient, str]
    ) -> None:
        client, key = private_client_with_key
        _install_adapters(client)
        resp = client.get("/api/v1/history/performance", headers={API_KEY_HEADER: key})
        assert resp.status_code == 503
        assert "gateway" in resp.json()["detail"]

    def test_portfolio_snapshots_503_when_gateway_none(
        self, private_client_with_key: tuple[TestClient, str]
    ) -> None:
        client, key = private_client_with_key
        _install_adapters(client)
        resp = client.get(
            "/api/v1/history/portfolio-snapshots",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 503
        assert "gateway" in resp.json()["detail"]

    def test_backtests_503_when_mongo_none(
        self, private_client_with_key: tuple[TestClient, str]
    ) -> None:
        client, key = private_client_with_key
        _install_adapters(client)
        resp = client.get("/api/v1/history/backtests", headers={API_KEY_HEADER: key})
        assert resp.status_code == 503
        assert "mongo" in resp.json()["detail"]

    def test_signals_503_when_mongo_none(
        self, private_client_with_key: tuple[TestClient, str]
    ) -> None:
        client, key = private_client_with_key
        _install_adapters(client)
        resp = client.get(
            "/api/v1/history/signals?date=2026-05-06",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 503
        assert "mongo" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Happy paths — stubbed adapters return shaped models, verify response body
# ---------------------------------------------------------------------------


class TestEquityCurve:
    def test_returns_adapter_rows(self, private_client_with_key: tuple[TestClient, str]) -> None:
        client, key = private_client_with_key
        rows = [
            EquityPoint(time=_FIXED_TIME, strategy_id="csm-set", equity=100.0),
            EquityPoint(time=_FIXED_TIME, strategy_id="csm-set", equity=101.5),
        ]
        _install_adapters(client, postgres=_stub_postgres(read_equity_curve=rows))

        resp = client.get(
            "/api/v1/history/equity-curve?days=30",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        assert body[0]["equity"] == 100.0
        assert body[0]["strategy_id"] == "csm-set"

    def test_days_out_of_range_returns_422(
        self, private_client_with_key: tuple[TestClient, str]
    ) -> None:
        client, key = private_client_with_key
        _install_adapters(client, postgres=_stub_postgres(read_equity_curve=[]))
        resp = client.get(
            "/api/v1/history/equity-curve?days=0",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 422

    def test_passes_strategy_id_and_days_to_adapter(
        self, private_client_with_key: tuple[TestClient, str]
    ) -> None:
        client, key = private_client_with_key
        stub = _stub_postgres(read_equity_curve=[])
        _install_adapters(client, postgres=stub)
        resp = client.get(
            "/api/v1/history/equity-curve?strategy_id=other&days=7",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 200
        cast(AsyncMock, stub.read_equity_curve).assert_awaited_once_with("other", 7)


class TestTrades:
    def test_returns_adapter_rows(self, private_client_with_key: tuple[TestClient, str]) -> None:
        client, key = private_client_with_key
        rows = [
            TradeRow(
                time=_FIXED_TIME,
                strategy_id="csm-set",
                symbol="PTT",
                side="buy",
                quantity=100.0,
                price=35.0,
                commission=5.25,
            ),
        ]
        _install_adapters(client, postgres=_stub_postgres(read_trade_history=rows))
        resp = client.get(
            "/api/v1/history/trades?limit=10",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["symbol"] == "PTT"
        assert body[0]["side"] == "buy"

    def test_passes_strategy_id_and_limit_to_adapter(
        self, private_client_with_key: tuple[TestClient, str]
    ) -> None:
        client, key = private_client_with_key
        stub = _stub_postgres(read_trade_history=[])
        _install_adapters(client, postgres=stub)
        resp = client.get(
            "/api/v1/history/trades?strategy_id=other&limit=5",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 200
        cast(AsyncMock, stub.read_trade_history).assert_awaited_once_with("other", 5)


class TestPerformance:
    def test_returns_adapter_rows(self, private_client_with_key: tuple[TestClient, str]) -> None:
        client, key = private_client_with_key
        rows = [
            DailyPerformanceRow(
                time=_FIXED_TIME,
                strategy_id="csm-set",
                daily_return=0.012,
                cumulative_return=0.150,
                total_value=1_000_000.0,
                cash_balance=10_000.0,
                max_drawdown=-0.08,
                sharpe_ratio=1.4,
                metadata={"symbols_fetched": 50},
            ),
        ]
        _install_adapters(client, gateway=_stub_gateway(read_daily_performance=rows))
        resp = client.get(
            "/api/v1/history/performance?days=7",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["daily_return"] == 0.012
        assert body[0]["metadata"] == {"symbols_fetched": 50}


class TestPortfolioSnapshots:
    def test_returns_adapter_rows(self, private_client_with_key: tuple[TestClient, str]) -> None:
        client, key = private_client_with_key
        rows = [
            PortfolioSnapshotRow(
                time=_FIXED_TIME,
                total_portfolio=1_010_000.0,
                weighted_return=0.012,
                combined_drawdown=-0.05,
                active_strategies=1,
                allocation={"csm-set": 1.0},
            ),
        ]
        _install_adapters(client, gateway=_stub_gateway(read_portfolio_snapshots=rows))
        resp = client.get(
            "/api/v1/history/portfolio-snapshots?days=14",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["allocation"] == {"csm-set": 1.0}
        assert body[0]["active_strategies"] == 1


class TestBacktests:
    def test_returns_adapter_rows(self, private_client_with_key: tuple[TestClient, str]) -> None:
        client, key = private_client_with_key
        rows = [
            BacktestSummaryRow(
                run_id="01JTESTRUN",
                strategy_id="csm-set",
                created_at=_FIXED_TIME,
                metrics={"sharpe": 1.42, "max_dd": -0.18},
            ),
        ]
        _install_adapters(client, mongo=_stub_mongo(list_backtest_results=rows))
        resp = client.get(
            "/api/v1/history/backtests?limit=5",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["run_id"] == "01JTESTRUN"
        assert body[0]["metrics"]["sharpe"] == 1.42


class TestSignals:
    def test_404_when_adapter_returns_none(
        self, private_client_with_key: tuple[TestClient, str]
    ) -> None:
        client, key = private_client_with_key
        _install_adapters(client, mongo=_stub_mongo(read_signal_snapshot=None))
        resp = client.get(
            "/api/v1/history/signals?date=2026-05-06",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 404
        assert "No signal snapshot" in resp.json()["detail"]

    def test_returns_adapter_doc(self, private_client_with_key: tuple[TestClient, str]) -> None:
        client, key = private_client_with_key
        doc = SignalSnapshotDoc(
            strategy_id="csm-set",
            date=_FIXED_TIME,
            rankings=[
                {"symbol": "PTT", "rank": 0.95, "quintile": 5},
                {"symbol": "BBL", "rank": 0.10, "quintile": 1},
            ],
        )
        _install_adapters(client, mongo=_stub_mongo(read_signal_snapshot=doc))
        resp = client.get(
            "/api/v1/history/signals?date=2026-05-06",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["strategy_id"] == "csm-set"
        assert len(body["rankings"]) == 2

    def test_promotes_date_to_utc_midnight(
        self, private_client_with_key: tuple[TestClient, str]
    ) -> None:
        client, key = private_client_with_key
        stub = _stub_mongo(read_signal_snapshot=None)
        _install_adapters(client, mongo=stub)
        resp = client.get(
            "/api/v1/history/signals?date=2026-05-06&strategy_id=alpha",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 404
        cast(AsyncMock, stub.read_signal_snapshot).assert_awaited_once_with(
            "alpha",
            datetime(2026, 5, 6, 0, 0, 0, tzinfo=UTC),
        )

    def test_invalid_date_returns_422(
        self, private_client_with_key: tuple[TestClient, str]
    ) -> None:
        client, key = private_client_with_key
        _install_adapters(client, mongo=_stub_mongo(read_signal_snapshot=None))
        resp = client.get(
            "/api/v1/history/signals?date=not-a-date",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 422

    def test_missing_date_returns_422(
        self, private_client_with_key: tuple[TestClient, str]
    ) -> None:
        client, key = private_client_with_key
        _install_adapters(client, mongo=_stub_mongo(read_signal_snapshot=None))
        resp = client.get("/api/v1/history/signals", headers={API_KEY_HEADER: key})
        assert resp.status_code == 422
