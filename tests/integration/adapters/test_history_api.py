"""End-to-end ``infra_db`` tests for the ``/api/v1/history/*`` endpoints.

Requires ``quant-infra-db`` running on ``quant-network`` with the
csm-set schemas live. Skipped by default — run with ``pytest -m infra_db``.

These tests write seed rows via the live ``AdapterManager`` (from the
shared ``adapter_manager`` fixture in :mod:`tests.integration.adapters.conftest`)
and then fetch them through the FastAPI router using ``TestClient``,
overriding ``app.state.adapters`` for the duration of each test.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from api.security import API_KEY_HEADER
from fastapi.testclient import TestClient

from csm.adapters import AdapterManager

pytestmark = pytest.mark.infra_db

TEST_STRATEGY_ID: str = "test-csm-set"
TEST_RUN_ID_PREFIX: str = "test-csm-set-"


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _equity_series(n: int = 10) -> pd.Series:
    base = datetime(2026, 4, 1, tzinfo=UTC)
    index = pd.DatetimeIndex([base + timedelta(days=i) for i in range(n)], tz="UTC")
    return pd.Series([100.0 + i for i in range(n)], index=index, dtype="float64")


def _trades_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-04-01", "2026-04-02", "2026-04-03"], utc=True),
            "symbol": ["PTT", "PTT", "BBL"],
            "side": ["buy", "sell", "buy"],
            "quantity": [100.0, 100.0, 50.0],
            "price": [40.0, 42.0, 150.0],
            "commission": [6.42, 6.74, 12.05],
        }
    )


# ---------------------------------------------------------------------------
# Equity curve / trades — Postgres-backed
# ---------------------------------------------------------------------------


class TestEquityCurveLive:
    async def test_returns_seeded_rows_in_order(
        self,
        adapter_manager: AdapterManager,
        private_client_with_key: tuple[TestClient, str],
    ) -> None:
        if adapter_manager.postgres is None:
            pytest.skip("Postgres adapter not available")

        await adapter_manager.postgres.write_equity_curve(TEST_STRATEGY_ID, _equity_series(10))

        client, key = private_client_with_key
        client.app.state.adapters = adapter_manager  # type: ignore[attr-defined]
        resp = client.get(
            f"/api/v1/history/equity-curve?strategy_id={TEST_STRATEGY_ID}&days=30",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 10
        # Ascending by time.
        timestamps = [row["time"] for row in body]
        assert timestamps == sorted(timestamps)
        assert all(row["strategy_id"] == TEST_STRATEGY_ID for row in body)


class TestTradesLive:
    async def test_returns_seeded_rows(
        self,
        adapter_manager: AdapterManager,
        private_client_with_key: tuple[TestClient, str],
    ) -> None:
        if adapter_manager.postgres is None:
            pytest.skip("Postgres adapter not available")

        await adapter_manager.postgres.write_trade_history(TEST_STRATEGY_ID, _trades_df())

        client, key = private_client_with_key
        client.app.state.adapters = adapter_manager  # type: ignore[attr-defined]
        resp = client.get(
            f"/api/v1/history/trades?strategy_id={TEST_STRATEGY_ID}&limit=10",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 3
        symbols = {row["symbol"] for row in body}
        assert symbols == {"PTT", "BBL"}


# ---------------------------------------------------------------------------
# Performance / portfolio snapshots — Gateway-backed
# ---------------------------------------------------------------------------


class TestPerformanceLive:
    async def test_returns_seeded_metrics(
        self,
        adapter_manager: AdapterManager,
        private_client_with_key: tuple[TestClient, str],
    ) -> None:
        if adapter_manager.gateway is None:
            pytest.skip("Gateway adapter not available")

        for offset in range(3):
            await adapter_manager.gateway.write_daily_performance(
                TEST_STRATEGY_ID,
                datetime(2026, 4, 1, tzinfo=UTC) + timedelta(days=offset),
                {
                    "daily_return": 0.01 + offset * 0.001,
                    "cumulative_return": 0.05 + offset * 0.005,
                    "total_value": 1_000_000.0,
                    "cash_balance": 10_000.0,
                    "max_drawdown": -0.04,
                    "sharpe_ratio": 1.3,
                    "metadata": {"symbols_fetched": 50 + offset},
                },
            )

        client, key = private_client_with_key
        client.app.state.adapters = adapter_manager  # type: ignore[attr-defined]
        resp = client.get(
            f"/api/v1/history/performance?strategy_id={TEST_STRATEGY_ID}&days=30",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 3
        timestamps = [row["time"] for row in body]
        assert timestamps == sorted(timestamps)


class TestPortfolioSnapshotsLive:
    async def test_returns_seeded_snapshots(
        self,
        adapter_manager: AdapterManager,
        private_client_with_key: tuple[TestClient, str],
    ) -> None:
        if adapter_manager.gateway is None:
            pytest.skip("Gateway adapter not available")

        for offset in range(2):
            await adapter_manager.gateway.write_portfolio_snapshot(
                datetime(2026, 4, 10, tzinfo=UTC) + timedelta(days=offset),
                {
                    "total_portfolio": 1_010_000.0 + offset * 1_000.0,
                    "weighted_return": 0.012,
                    "combined_drawdown": -0.05,
                    "active_strategies": 1,
                    "allocation": {TEST_STRATEGY_ID: 1.0},
                },
            )

        client, key = private_client_with_key
        client.app.state.adapters = adapter_manager  # type: ignore[attr-defined]
        resp = client.get(
            "/api/v1/history/portfolio-snapshots?days=30",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) >= 2
        # The seeded rows carry our test allocation key.
        seeded = [row for row in body if TEST_STRATEGY_ID in row.get("allocation", {})]
        assert len(seeded) == 2


# ---------------------------------------------------------------------------
# Backtests / signals — Mongo-backed
# ---------------------------------------------------------------------------


class TestBacktestsLive:
    async def test_lists_seeded_results(
        self,
        adapter_manager: AdapterManager,
        private_client_with_key: tuple[TestClient, str],
    ) -> None:
        if adapter_manager.mongo is None:
            pytest.skip("Mongo adapter not available")

        for index in range(2):
            await adapter_manager.mongo.write_backtest_result(
                {
                    "run_id": f"{TEST_RUN_ID_PREFIX}history-{index:03d}",
                    "strategy_id": TEST_STRATEGY_ID,
                    "created_at": datetime(2026, 4, 20, tzinfo=UTC) + timedelta(hours=index),
                    "config": {"formation_months": 12},
                    "metrics": {"sharpe": 1.4 + 0.1 * index, "max_dd": -0.18},
                    "equity_curve": {"2026-01-31": 100.0},
                    "trades": [],
                }
            )

        client, key = private_client_with_key
        client.app.state.adapters = adapter_manager  # type: ignore[attr-defined]
        resp = client.get(
            f"/api/v1/history/backtests?strategy_id={TEST_STRATEGY_ID}&limit=5",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 200
        body = resp.json()
        run_ids = {row["run_id"] for row in body}
        assert any(rid.startswith(TEST_RUN_ID_PREFIX) for rid in run_ids)


class TestSignalsLive:
    async def test_returns_seeded_snapshot(
        self,
        adapter_manager: AdapterManager,
        private_client_with_key: tuple[TestClient, str],
    ) -> None:
        if adapter_manager.mongo is None:
            pytest.skip("Mongo adapter not available")

        snapshot_at = datetime(2026, 4, 15, tzinfo=UTC)
        rankings = [
            {"symbol": "PTT", "rank": 0.95, "quintile": 5},
            {"symbol": "BBL", "rank": 0.10, "quintile": 1},
        ]
        await adapter_manager.mongo.write_signal_snapshot(TEST_STRATEGY_ID, snapshot_at, rankings)

        client, key = private_client_with_key
        client.app.state.adapters = adapter_manager  # type: ignore[attr-defined]
        resp = client.get(
            f"/api/v1/history/signals?strategy_id={TEST_STRATEGY_ID}&date=2026-04-15",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["strategy_id"] == TEST_STRATEGY_ID
        assert len(body["rankings"]) == 2

    async def test_returns_404_for_missing_date(
        self,
        adapter_manager: AdapterManager,
        private_client_with_key: tuple[TestClient, str],
    ) -> None:
        if adapter_manager.mongo is None:
            pytest.skip("Mongo adapter not available")

        client, key = private_client_with_key
        client.app.state.adapters = adapter_manager  # type: ignore[attr-defined]
        resp = client.get(
            f"/api/v1/history/signals?strategy_id={TEST_STRATEGY_ID}&date=1999-12-31",
            headers={API_KEY_HEADER: key},
        )
        assert resp.status_code == 404
