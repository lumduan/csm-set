"""Integration tests for ``GatewayAdapter`` against the real ``db_gateway``.

Marked ``@pytest.mark.infra_db`` — skipped by default, selected only when
``CSM_DB_GATEWAY_DSN`` is set and the ``infra_db`` marker is included.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from csm.adapters.gateway import GatewayAdapter
from csm.adapters.models import DailyPerformanceRow, PortfolioSnapshotRow

pytestmark = pytest.mark.infra_db

TEST_STRATEGY_ID: str = "test-csm-set"


class TestWriteDailyPerformance:
    async def test_write_and_read_round_trip(self, gateway_adapter: GatewayAdapter) -> None:
        gw = gateway_adapter
        date = datetime(2024, 6, 15, tzinfo=UTC)
        metrics = {
            "daily_return": 0.012,
            "cumulative_return": 0.15,
            "total_value": 1_000_000.0,
            "cash_balance": 50_000.0,
            "max_drawdown": -0.05,
            "sharpe_ratio": 1.42,
        }
        await gw.write_daily_performance(TEST_STRATEGY_ID, date, metrics)

        rows = await gw.read_daily_performance(TEST_STRATEGY_ID, days=1)
        assert len(rows) == 1
        row = rows[0]
        assert isinstance(row, DailyPerformanceRow)
        assert row.strategy_id == TEST_STRATEGY_ID
        assert row.daily_return == 0.012
        assert row.cumulative_return == 0.15
        assert row.total_value == 1_000_000.0
        assert row.cash_balance == 50_000.0
        assert row.max_drawdown == -0.05
        assert row.sharpe_ratio == 1.42
        assert row.metadata == metrics

    async def test_write_is_idempotent(self, gateway_adapter: GatewayAdapter) -> None:
        gw = gateway_adapter
        date = datetime(2024, 6, 15, tzinfo=UTC)

        # First write
        await gw.write_daily_performance(
            TEST_STRATEGY_ID, date, {"daily_return": 0.01, "sharpe_ratio": 1.0}
        )
        # Second write with different values
        await gw.write_daily_performance(
            TEST_STRATEGY_ID, date, {"daily_return": 0.02, "sharpe_ratio": 2.0}
        )

        rows = await gw.read_daily_performance(TEST_STRATEGY_ID, days=1)
        assert len(rows) == 1  # No duplicate
        assert rows[0].daily_return == 0.02  # Latest value
        assert rows[0].sharpe_ratio == 2.0  # Latest value
        assert rows[0].metadata == {"daily_return": 0.02, "sharpe_ratio": 2.0}

    async def test_read_respects_days_parameter(self, gateway_adapter: GatewayAdapter) -> None:
        gw = gateway_adapter
        base = datetime(2024, 6, 1, tzinfo=UTC)
        for i in range(5):
            date = base + timedelta(days=i)
            await gw.write_daily_performance(
                TEST_STRATEGY_ID, date, {"daily_return": i / 100.0, "sharpe_ratio": 1.0}
            )

        rows = await gw.read_daily_performance(TEST_STRATEGY_ID, days=3)
        assert len(rows) == 3

    async def test_read_ascending_time_order(self, gateway_adapter: GatewayAdapter) -> None:
        gw = gateway_adapter
        dates = [
            datetime(2024, 6, 1, tzinfo=UTC),
            datetime(2024, 6, 2, tzinfo=UTC),
            datetime(2024, 6, 3, tzinfo=UTC),
        ]
        for i, date in enumerate(dates):
            await gw.write_daily_performance(
                TEST_STRATEGY_ID, date, {"daily_return": i / 100.0, "sharpe_ratio": 1.0}
            )

        rows = await gw.read_daily_performance(TEST_STRATEGY_ID, days=5)
        assert len(rows) == 3
        # Should be ascending by time
        assert rows[0].time < rows[1].time < rows[2].time


class TestWritePortfolioSnapshot:
    async def test_write_and_read_round_trip(self, gateway_adapter: GatewayAdapter) -> None:
        gw = gateway_adapter
        date = datetime(2024, 6, 15, tzinfo=UTC)
        snapshot = {
            "total_portfolio": 1_500_000.0,
            "weighted_return": 0.008,
            "combined_drawdown": -0.03,
            "active_strategies": 1,
            "allocation": {"csm-set": 1.0},
        }
        await gw.write_portfolio_snapshot(date, snapshot)

        rows = await gw.read_portfolio_snapshots(days=1)
        assert len(rows) == 1
        row = rows[0]
        assert isinstance(row, PortfolioSnapshotRow)
        assert row.total_portfolio == 1_500_000.0
        assert row.weighted_return == 0.008
        assert row.combined_drawdown == -0.03
        assert row.active_strategies == 1
        assert row.allocation == {"csm-set": 1.0}

    async def test_write_is_idempotent(self, gateway_adapter: GatewayAdapter) -> None:
        gw = gateway_adapter
        date = datetime(2024, 6, 15, tzinfo=UTC)

        await gw.write_portfolio_snapshot(
            date, {"total_portfolio": 1_000_000.0, "allocation": {"csm-set": 1.0}}
        )
        await gw.write_portfolio_snapshot(
            date, {"total_portfolio": 1_100_000.0, "allocation": {"csm-set": 0.6, "mean-rev": 0.4}}
        )

        rows = await gw.read_portfolio_snapshots(days=1)
        assert len(rows) == 1  # No duplicate
        assert rows[0].total_portfolio == 1_100_000.0  # Latest value
        assert rows[0].allocation == {"csm-set": 0.6, "mean-rev": 0.4}

    async def test_read_respects_days_parameter(self, gateway_adapter: GatewayAdapter) -> None:
        gw = gateway_adapter
        base = datetime(2024, 6, 1, tzinfo=UTC)
        for i in range(5):
            date = base + timedelta(days=i)
            await gw.write_portfolio_snapshot(
                date, {"total_portfolio": 1_000_000.0 + i * 10000, "allocation": {}}
            )

        rows = await gw.read_portfolio_snapshots(days=3)
        assert len(rows) == 3

    async def test_read_ascending_time_order(self, gateway_adapter: GatewayAdapter) -> None:
        gw = gateway_adapter
        dates = [
            datetime(2024, 6, 1, tzinfo=UTC),
            datetime(2024, 6, 2, tzinfo=UTC),
            datetime(2024, 6, 3, tzinfo=UTC),
        ]
        for date in dates:
            await gw.write_portfolio_snapshot(
                date, {"total_portfolio": 1_000_000.0, "allocation": {}}
            )

        rows = await gw.read_portfolio_snapshots(days=5)
        assert len(rows) == 3
        assert rows[0].time < rows[1].time < rows[2].time
