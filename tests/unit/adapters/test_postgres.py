"""Unit tests for ``PostgresAdapter`` with mocked ``asyncpg`` pool."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from csm.adapters.models import BacktestLogRow, EquityPoint, TradeRow
from csm.adapters.postgres import PostgresAdapter

DSN: str = "postgresql://test:test@localhost:5432/db_csm_set"


def _make_pool() -> AsyncMock:
    """Build an ``AsyncMock`` shaped like ``asyncpg.Pool``."""
    pool = AsyncMock()
    pool.executemany = AsyncMock()
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
            adapter = PostgresAdapter(DSN)
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
            adapter = PostgresAdapter(DSN)
            await adapter.connect()
            await adapter.connect()

        create.assert_awaited_once()

    async def test_close_calls_pool_close(self) -> None:
        pool = _make_pool()
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = PostgresAdapter(DSN)
            await adapter.connect()
            await adapter.close()

        pool.close.assert_awaited_once()

    async def test_close_without_connect_is_noop(self) -> None:
        adapter = PostgresAdapter(DSN)
        # Must not raise.
        await adapter.close()

    async def test_close_is_idempotent(self) -> None:
        pool = _make_pool()
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = PostgresAdapter(DSN)
            await adapter.connect()
            await adapter.close()
            await adapter.close()

        pool.close.assert_awaited_once()

    async def test_aenter_aexit(self) -> None:
        pool = _make_pool()
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            async with PostgresAdapter(DSN) as adapter:
                assert isinstance(adapter, PostgresAdapter)

        pool.close.assert_awaited_once()

    async def test_dsn_property(self) -> None:
        adapter = PostgresAdapter(DSN)
        assert adapter.dsn == DSN


class TestPing:
    async def test_ping_returns_true_when_select_1(self) -> None:
        pool = _make_pool()
        pool.fetchval = AsyncMock(return_value=1)
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = PostgresAdapter(DSN)
            await adapter.connect()
            assert await adapter.ping() is True

        pool.fetchval.assert_awaited_once_with("SELECT 1")

    async def test_ping_returns_false_when_unexpected_value(self) -> None:
        pool = _make_pool()
        pool.fetchval = AsyncMock(return_value=0)
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = PostgresAdapter(DSN)
            await adapter.connect()
            assert await adapter.ping() is False

    async def test_ping_raises_when_not_connected(self) -> None:
        adapter = PostgresAdapter(DSN)
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter.ping()


class TestWriteEquityCurve:
    async def test_executemany_called_with_252_tuples(self) -> None:
        pool = _make_pool()
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = PostgresAdapter(DSN)
            await adapter.connect()
            index = pd.date_range("2024-01-01", periods=252, freq="B", tz="UTC")
            series = pd.Series(range(252), index=index, dtype="float64")
            count = await adapter.write_equity_curve("csm-set", series)

        assert count == 252
        pool.executemany.assert_awaited_once()
        sql, rows = pool.executemany.await_args.args
        assert "INSERT INTO equity_curve" in sql
        assert "ON CONFLICT (time, strategy_id) DO UPDATE" in sql
        assert len(rows) == 252
        assert rows[0][1] == "csm-set"
        assert isinstance(rows[0][2], float)

    async def test_empty_series_skips_executemany(self) -> None:
        pool = _make_pool()
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = PostgresAdapter(DSN)
            await adapter.connect()
            empty = pd.Series(dtype="float64")
            count = await adapter.write_equity_curve("csm-set", empty)

        assert count == 0
        pool.executemany.assert_not_awaited()

    async def test_raises_when_not_connected(self) -> None:
        adapter = PostgresAdapter(DSN)
        empty = pd.Series(dtype="float64")
        with pytest.raises(RuntimeError, match="not connected"):
            await adapter.write_equity_curve("csm-set", empty)


class TestWriteTradeHistory:
    @staticmethod
    def _trades_df() -> pd.DataFrame:
        return pd.DataFrame(
            {
                "time": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"], utc=True),
                "symbol": ["PTT", "PTT", "BBL"],
                "side": ["buy", "sell", "buy"],
                "quantity": [100, 100, 50],
                "price": [40.0, 42.0, 150.0],
                "commission": [6.42, 6.74, 12.05],
            }
        )

    async def test_executemany_called_with_n_tuples(self) -> None:
        pool = _make_pool()
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = PostgresAdapter(DSN)
            await adapter.connect()
            count = await adapter.write_trade_history("csm-set", self._trades_df())

        assert count == 3
        pool.executemany.assert_awaited_once()
        sql, rows = pool.executemany.await_args.args
        assert "INSERT INTO trade_history" in sql
        assert "ON CONFLICT (strategy_id, time, symbol, side) DO UPDATE" in sql
        assert len(rows) == 3
        assert rows[0][1] == "csm-set"  # strategy_id
        assert rows[0][2] == "PTT"

    async def test_empty_dataframe_skips_executemany(self) -> None:
        pool = _make_pool()
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = PostgresAdapter(DSN)
            await adapter.connect()
            count = await adapter.write_trade_history("csm-set", pd.DataFrame())

        assert count == 0
        pool.executemany.assert_not_awaited()

    async def test_missing_columns_raises_keyerror(self) -> None:
        pool = _make_pool()
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = PostgresAdapter(DSN)
            await adapter.connect()
            bad = pd.DataFrame({"time": [pd.Timestamp("2024-01-02", tz="UTC")]})
            with pytest.raises(KeyError, match="missing required columns"):
                await adapter.write_trade_history("csm-set", bad)


class TestWriteBacktestLog:
    async def test_execute_called_with_json_serialised_payloads(self) -> None:
        pool = _make_pool()
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = PostgresAdapter(DSN)
            await adapter.connect()
            config = {"top_n": 5, "rebalance": "monthly"}
            summary = {"sharpe": 1.42, "max_dd": -0.18}
            await adapter.write_backtest_log("run-001", "csm-set", config, summary)

        pool.execute.assert_awaited_once()
        sql, run_id, strategy_id, started_at, config_arg, summary_arg = pool.execute.await_args.args
        assert "INSERT INTO backtest_log" in sql
        assert "ON CONFLICT (run_id) DO NOTHING" in sql
        assert run_id == "run-001"
        assert strategy_id == "csm-set"
        assert isinstance(started_at, datetime)
        assert config_arg == config
        assert summary_arg == summary


class TestReads:
    async def test_read_equity_curve_returns_models(self) -> None:
        pool = _make_pool()
        records = [
            {
                "time": datetime(2024, 1, 2, tzinfo=UTC),
                "strategy_id": "csm-set",
                "equity": 100.0,
            },
            {
                "time": datetime(2024, 1, 3, tzinfo=UTC),
                "strategy_id": "csm-set",
                "equity": 101.5,
            },
        ]
        pool.fetch = AsyncMock(return_value=records)
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = PostgresAdapter(DSN)
            await adapter.connect()
            result = await adapter.read_equity_curve("csm-set", days=30)

        sql, strategy_id, days = pool.fetch.await_args.args
        assert "SELECT time, strategy_id, equity" in sql
        assert "ORDER BY time ASC" in sql
        assert strategy_id == "csm-set"
        assert days == 30
        assert len(result) == 2
        assert all(isinstance(p, EquityPoint) for p in result)
        assert result[0].equity == 100.0

    async def test_read_trade_history_returns_models(self) -> None:
        pool = _make_pool()
        records = [
            {
                "time": datetime(2024, 1, 2, tzinfo=UTC),
                "strategy_id": "csm-set",
                "symbol": "PTT",
                "side": "buy",
                "quantity": 100.0,
                "price": 40.0,
                "commission": 6.42,
            }
        ]
        pool.fetch = AsyncMock(return_value=records)
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = PostgresAdapter(DSN)
            await adapter.connect()
            result = await adapter.read_trade_history("csm-set", limit=10)

        sql, strategy_id, limit = pool.fetch.await_args.args
        assert "ORDER BY time DESC" in sql
        assert strategy_id == "csm-set"
        assert limit == 10
        assert len(result) == 1
        assert isinstance(result[0], TradeRow)
        assert result[0].symbol == "PTT"

    async def test_read_backtest_log_with_strategy_filter(self) -> None:
        pool = _make_pool()
        records = [
            {
                "run_id": "run-001",
                "strategy_id": "csm-set",
                "created_at": datetime(2024, 1, 2, tzinfo=UTC),
                "config": {"top_n": 5},
                "summary": {"sharpe": 1.5},
            }
        ]
        pool.fetch = AsyncMock(return_value=records)
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = PostgresAdapter(DSN)
            await adapter.connect()
            result = await adapter.read_backtest_log("csm-set", limit=20)

        sql, strategy_id, limit = pool.fetch.await_args.args
        assert "ORDER BY started_at DESC" in sql
        assert strategy_id == "csm-set"
        assert limit == 20
        assert len(result) == 1
        assert isinstance(result[0], BacktestLogRow)
        assert result[0].run_id == "run-001"
        assert result[0].config == {"top_n": 5}
        assert result[0].summary == {"sharpe": 1.5}

    async def test_read_backtest_log_with_none_filter(self) -> None:
        pool = _make_pool()
        pool.fetch = AsyncMock(return_value=[])
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = PostgresAdapter(DSN)
            await adapter.connect()
            result = await adapter.read_backtest_log(None, limit=5)

        _sql, strategy_id, limit = pool.fetch.await_args.args
        assert strategy_id is None
        assert limit == 5
        assert result == []

    async def test_read_backtest_log_handles_non_dict_jsonb(self) -> None:
        """Coerce stray JSONB values that were not decoded into dicts."""
        pool = _make_pool()
        records = [
            {
                "run_id": "run-002",
                "strategy_id": "csm-set",
                "created_at": datetime(2024, 1, 2, tzinfo=UTC),
                "config": None,
                "summary": "not-a-dict",
            }
        ]
        pool.fetch = AsyncMock(return_value=records)
        with patch("asyncpg.create_pool", new=AsyncMock(return_value=pool)):
            adapter = PostgresAdapter(DSN)
            await adapter.connect()
            result = await adapter.read_backtest_log()

        assert result[0].config == {}
        assert result[0].summary == {}
