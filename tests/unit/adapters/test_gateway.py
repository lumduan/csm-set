"""Unit tests for ``GatewayAdapter`` with mocked ``asyncpg`` pool."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from csm.adapters.gateway import GatewayAdapter
from csm.adapters.models import DailyPerformanceRow, PortfolioSnapshotRow

DSN: str = "postgresql://test:test@localhost:5432/db_gateway"


def _make_pool() -> AsyncMock:
    """Build an ``AsyncMock`` shaped like ``asyncpg.Pool``."""
    pool = AsyncMock()
    pool.execute = AsyncMock()
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchval = AsyncMock(return_value=1)
    pool.close = AsyncMock()
    return pool


class TestLifecycle:
    async def test_connect_creates_pool_with_expected_args(self) -> None:
        pool = _make_pool()
        create = AsyncMock(return_value=pool)
        with patch("asyncpg.create_pool", new=create):
            adapter = GatewayAdapter(DSN)
            await adapter.connect()

        create.assert_awaited_once()
        kwargs = create.call_args.kwargs
        assert kwargs["dsn"] == DSN
        assert kwargs["min_size"] == 2
        assert kwargs["max_size"] == 10
        assert kwargs["command_timeout"] == 30
        assert callable(kwargs["init"])

    async def test_connect_is_idempotent(self) -> None:
        pool = _make_pool()
        create = AsyncMock(return_value=pool)
        with patch("asyncpg.create_pool", new=create):
            adapter = GatewayAdapter(DSN)
            await adapter.connect()
            await adapter.connect()

        create.assert_awaited_once()

    async def test_close_calls_pool_close(self) -> None:
        pool = _make_pool()
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = GatewayAdapter(DSN)
            await adapter.connect()
            await adapter.close()

        pool.close.assert_awaited_once()

    async def test_close_without_connect_is_noop(self) -> None:
        adapter = GatewayAdapter(DSN)
        await adapter.close()

    async def test_close_is_idempotent(self) -> None:
        pool = _make_pool()
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = GatewayAdapter(DSN)
            await adapter.connect()
            await adapter.close()
            await adapter.close()

        pool.close.assert_awaited_once()

    async def test_aenter_aexit(self) -> None:
        pool = _make_pool()
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            async with GatewayAdapter(DSN) as adapter:
                assert isinstance(adapter, GatewayAdapter)

        pool.close.assert_awaited_once()

    async def test_dsn_property(self) -> None:
        adapter = GatewayAdapter(DSN)
        assert adapter.dsn == DSN


class TestPing:
    async def test_ping_returns_true_when_select_1(self) -> None:
        pool = _make_pool()
        pool.fetchval = AsyncMock(return_value=1)
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = GatewayAdapter(DSN)
            await adapter.connect()
            assert await adapter.ping() is True

        pool.fetchval.assert_awaited_once_with("SELECT 1")

    async def test_ping_returns_false_when_unexpected_value(self) -> None:
        pool = _make_pool()
        pool.fetchval = AsyncMock(return_value=0)
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = GatewayAdapter(DSN)
            await adapter.connect()
            assert await adapter.ping() is False

    async def test_ping_raises_when_not_connected(self) -> None:
        adapter = GatewayAdapter(DSN)
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter.ping()


class TestWriteDailyPerformance:
    async def test_execute_called_with_full_metrics(self) -> None:
        pool = _make_pool()
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = GatewayAdapter(DSN)
            await adapter.connect()
            metrics = {
                "daily_return": 0.012,
                "cumulative_return": 0.15,
                "total_value": 1_000_000.0,
                "cash_balance": 50_000.0,
                "max_drawdown": -0.05,
                "sharpe_ratio": 1.42,
                "extra_field": "ignored_by_scalars",
            }
            date = datetime(2024, 6, 15, tzinfo=UTC)
            await adapter.write_daily_performance("csm-set", date, metrics)

        pool.execute.assert_awaited_once()
        args = pool.execute.await_args.args
        sql = args[0]
        assert "INSERT INTO daily_performance" in sql
        assert "ON CONFLICT (time, strategy_id) DO UPDATE" in sql
        assert args[1] == date
        assert args[2] == "csm-set"
        assert args[3] == 0.012  # daily_return
        assert args[4] == 0.15  # cumulative_return
        assert args[5] == 1_000_000.0  # total_value
        assert args[6] == 50_000.0  # cash_balance
        assert args[7] == -0.05  # max_drawdown
        assert args[8] == 1.42  # sharpe_ratio
        # metadata JSONB
        assert json.loads(args[9]) == metrics

    async def test_execute_called_with_sparse_metrics(self) -> None:
        """Missing scalar keys produce None values in positional params."""
        pool = _make_pool()
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = GatewayAdapter(DSN)
            await adapter.connect()
            date = datetime(2024, 6, 15, tzinfo=UTC)
            await adapter.write_daily_performance("csm-set", date, {})

        pool.execute.assert_awaited_once()
        args = pool.execute.await_args.args
        assert args[3] is None  # daily_return
        assert args[4] is None  # cumulative_return
        assert args[5] is None  # total_value
        assert args[6] is None  # cash_balance
        assert args[7] is None  # max_drawdown
        assert args[8] is None  # sharpe_ratio
        assert json.loads(args[9]) == {}

    async def test_raises_when_not_connected(self) -> None:
        adapter = GatewayAdapter(DSN)
        date = datetime(2024, 6, 15, tzinfo=UTC)
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter.write_daily_performance("csm-set", date, {})


class TestWritePortfolioSnapshot:
    async def test_execute_called_with_full_snapshot(self) -> None:
        pool = _make_pool()
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = GatewayAdapter(DSN)
            await adapter.connect()
            snapshot = {
                "total_portfolio": 1_500_000.0,
                "weighted_return": 0.008,
                "combined_drawdown": -0.03,
                "active_strategies": 1,
                "allocation": {"csm-set": 1.0},
            }
            date = datetime(2024, 6, 15, tzinfo=UTC)
            await adapter.write_portfolio_snapshot(date, snapshot)

        pool.execute.assert_awaited_once()
        args = pool.execute.await_args.args
        sql = args[0]
        assert "INSERT INTO portfolio_snapshot" in sql
        assert "ON CONFLICT (time) DO UPDATE" in sql
        assert args[1] == date
        assert args[2] == 1_500_000.0
        assert args[3] == 0.008
        assert args[4] == -0.03
        assert args[5] == 1
        assert json.loads(args[6]) == {"csm-set": 1.0}

    async def test_execute_called_with_sparse_snapshot(self) -> None:
        pool = _make_pool()
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = GatewayAdapter(DSN)
            await adapter.connect()
            date = datetime(2024, 6, 15, tzinfo=UTC)
            await adapter.write_portfolio_snapshot(date, {})

        pool.execute.assert_awaited_once()
        args = pool.execute.await_args.args
        assert args[2] is None  # total_portfolio
        assert args[3] is None  # weighted_return
        assert args[4] is None  # combined_drawdown
        assert args[5] == 0  # active_strategies default
        assert json.loads(args[6]) == {}  # allocation default

    async def test_raises_when_not_connected(self) -> None:
        adapter = GatewayAdapter(DSN)
        date = datetime(2024, 6, 15, tzinfo=UTC)
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter.write_portfolio_snapshot(date, {})


class TestReads:
    async def test_read_daily_performance_returns_models(self) -> None:
        pool = _make_pool()
        records = [
            {
                "time": datetime(2024, 1, 2, tzinfo=UTC),
                "strategy_id": "csm-set",
                "daily_return": 0.01,
                "cumulative_return": 0.05,
                "total_value": 1_000_000.0,
                "cash_balance": 100_000.0,
                "max_drawdown": -0.02,
                "sharpe_ratio": 1.5,
                "metadata": {"extra": "data"},
            },
            {
                "time": datetime(2024, 1, 3, tzinfo=UTC),
                "strategy_id": "csm-set",
                "daily_return": -0.005,
                "cumulative_return": 0.045,
                "total_value": 995_000.0,
                "cash_balance": 95_000.0,
                "max_drawdown": -0.025,
                "sharpe_ratio": 1.3,
                "metadata": {},
            },
        ]
        pool.fetch = AsyncMock(return_value=records)
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = GatewayAdapter(DSN)
            await adapter.connect()
            result = await adapter.read_daily_performance("csm-set", days=30)

        sql, strategy_id, days = pool.fetch.await_args.args
        assert "SELECT time, strategy_id, daily_return" in sql
        assert "ORDER BY time ASC" in sql
        assert strategy_id == "csm-set"
        assert days == 30
        assert len(result) == 2
        assert all(isinstance(p, DailyPerformanceRow) for p in result)
        assert result[0].daily_return == 0.01
        assert result[0].metadata == {"extra": "data"}
        assert result[1].daily_return == -0.005
        assert result[1].metadata == {}

    async def test_read_daily_performance_handles_nulls(self) -> None:
        pool = _make_pool()
        records = [
            {
                "time": datetime(2024, 1, 2, tzinfo=UTC),
                "strategy_id": "csm-set",
                "daily_return": None,
                "cumulative_return": None,
                "total_value": 1_000_000.0,
                "cash_balance": None,
                "max_drawdown": None,
                "sharpe_ratio": None,
                "metadata": None,
            }
        ]
        pool.fetch = AsyncMock(return_value=records)
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = GatewayAdapter(DSN)
            await adapter.connect()
            result = await adapter.read_daily_performance("csm-set")

        assert result[0].daily_return is None
        assert result[0].cumulative_return is None
        assert result[0].cash_balance is None
        assert result[0].metadata == {}

    async def test_read_portfolio_snapshots_returns_models(self) -> None:
        pool = _make_pool()
        records = [
            {
                "time": datetime(2024, 1, 2, tzinfo=UTC),
                "total_portfolio": 1_000_000.0,
                "weighted_return": 0.01,
                "combined_drawdown": -0.02,
                "active_strategies": 1,
                "allocation": {"csm-set": 1.0},
            },
            {
                "time": datetime(2024, 1, 3, tzinfo=UTC),
                "total_portfolio": 1_010_000.0,
                "weighted_return": 0.015,
                "combined_drawdown": -0.01,
                "active_strategies": 2,
                "allocation": {"csm-set": 0.6, "mean-rev": 0.4},
            },
        ]
        pool.fetch = AsyncMock(return_value=records)
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = GatewayAdapter(DSN)
            await adapter.connect()
            result = await adapter.read_portfolio_snapshots(days=30)

        sql, days = pool.fetch.await_args.args
        assert "SELECT time, total_portfolio, weighted_return" in sql
        assert "ORDER BY time ASC" in sql
        assert days == 30
        assert len(result) == 2
        assert all(isinstance(p, PortfolioSnapshotRow) for p in result)
        assert result[0].total_portfolio == 1_000_000.0
        assert result[0].allocation == {"csm-set": 1.0}
        assert result[1].allocation == {"csm-set": 0.6, "mean-rev": 0.4}
        assert result[1].active_strategies == 2

    async def test_read_portfolio_snapshots_handles_nulls(self) -> None:
        pool = _make_pool()
        records = [
            {
                "time": datetime(2024, 1, 2, tzinfo=UTC),
                "total_portfolio": None,
                "weighted_return": None,
                "combined_drawdown": None,
                "active_strategies": None,
                "allocation": None,
            }
        ]
        pool.fetch = AsyncMock(return_value=records)
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = GatewayAdapter(DSN)
            await adapter.connect()
            result = await adapter.read_portfolio_snapshots()

        assert result[0].total_portfolio is None
        assert result[0].weighted_return is None
        assert result[0].combined_drawdown is None
        assert result[0].active_strategies == 0
        assert result[0].allocation == {}

    async def test_read_daily_performance_raises_when_not_connected(self) -> None:
        adapter = GatewayAdapter(DSN)
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter.read_daily_performance("csm-set")

    async def test_read_portfolio_snapshots_raises_when_not_connected(self) -> None:
        adapter = GatewayAdapter(DSN)
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter.read_portfolio_snapshots()
