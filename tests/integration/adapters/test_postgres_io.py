"""Integration tests for ``PostgresAdapter`` against the real ``db_csm_set``.

Requires ``quant-postgres`` running on ``quant-network`` with the
``equity_curve``, ``trade_history``, and ``backtest_log`` schemas live.
Skipped by default — run with ``pytest -m infra_db``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from csm.adapters.models import BacktestLogRow, EquityPoint, TradeRow
from csm.adapters.postgres import PostgresAdapter

pytestmark = pytest.mark.infra_db

# Mirrors the constant in conftest.py — kept here to avoid a relative import
# that would break pytest's package discovery when other tests/*/adapters/
# trees also exist.
TEST_STRATEGY_ID: str = "test-csm-set"


def _equity_series(n: int = 10) -> pd.Series:
    base = datetime(2024, 1, 2, tzinfo=UTC)
    index = pd.DatetimeIndex([base + timedelta(days=i) for i in range(n)], tz="UTC")
    return pd.Series([100.0 + i for i in range(n)], index=index, dtype="float64")


def _trades_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"], utc=True),
            "symbol": ["PTT", "PTT", "BBL"],
            "side": ["buy", "sell", "buy"],
            "quantity": [100.0, 100.0, 50.0],
            "price": [40.0, 42.0, 150.0],
            "commission": [6.42, 6.74, 12.05],
        }
    )


async def test_write_equity_curve_idempotent(adapter: PostgresAdapter) -> None:
    series = _equity_series(10)

    first = await adapter.write_equity_curve(TEST_STRATEGY_ID, series)
    second = await adapter.write_equity_curve(TEST_STRATEGY_ID, series)

    assert first == 10
    assert second == 10

    pool = adapter._require_pool()  # noqa: SLF001
    count = await pool.fetchval(
        "SELECT count(*) FROM equity_curve WHERE strategy_id = $1",
        TEST_STRATEGY_ID,
    )
    assert count == 10


async def test_write_trade_history_idempotent(adapter: PostgresAdapter) -> None:
    trades = _trades_df()

    first = await adapter.write_trade_history(TEST_STRATEGY_ID, trades)
    second = await adapter.write_trade_history(TEST_STRATEGY_ID, trades)

    assert first == 3
    assert second == 3

    pool = adapter._require_pool()  # noqa: SLF001
    count = await pool.fetchval(
        "SELECT count(*) FROM trade_history WHERE strategy_id = $1",
        TEST_STRATEGY_ID,
    )
    assert count == 3


async def test_write_backtest_log_run_id_collision_is_no_op(
    adapter: PostgresAdapter,
) -> None:
    config = {"top_n": 5, "rebalance": "monthly"}
    summary_one = {"sharpe": 1.42}
    summary_two = {"sharpe": 9.99}

    await adapter.write_backtest_log("run-it-001", TEST_STRATEGY_ID, config, summary_one)
    await adapter.write_backtest_log("run-it-001", TEST_STRATEGY_ID, config, summary_two)

    pool = adapter._require_pool()  # noqa: SLF001
    rows = await pool.fetch("SELECT summary FROM backtest_log WHERE run_id = $1", "run-it-001")
    assert len(rows) == 1
    # First-write summary preserved (DO NOTHING on conflict).
    summary = rows[0]["summary"]
    if isinstance(summary, str):
        import json

        summary = json.loads(summary)
    assert summary == summary_one


async def test_read_equity_curve_returns_models_in_order(
    adapter: PostgresAdapter,
) -> None:
    series = _equity_series(20)
    await adapter.write_equity_curve(TEST_STRATEGY_ID, series)

    points = await adapter.read_equity_curve(TEST_STRATEGY_ID, days=5)

    assert len(points) == 5
    assert all(isinstance(p, EquityPoint) for p in points)
    assert all(p.strategy_id == TEST_STRATEGY_ID for p in points)
    times = [p.time for p in points]
    assert times == sorted(times)


async def test_read_trade_history_descending_with_limit(
    adapter: PostgresAdapter,
) -> None:
    trades = _trades_df()
    await adapter.write_trade_history(TEST_STRATEGY_ID, trades)

    rows = await adapter.read_trade_history(TEST_STRATEGY_ID, limit=2)

    assert len(rows) == 2
    assert all(isinstance(r, TradeRow) for r in rows)
    times = [r.time for r in rows]
    assert times == sorted(times, reverse=True)


async def test_read_backtest_log_filter_by_strategy(
    adapter: PostgresAdapter,
) -> None:
    await adapter.write_backtest_log(
        "run-it-002",
        TEST_STRATEGY_ID,
        {"top_n": 5},
        {"sharpe": 1.5, "trades": 100},
    )

    rows = await adapter.read_backtest_log(TEST_STRATEGY_ID, limit=10)

    assert len(rows) >= 1
    matching = [r for r in rows if r.run_id == "run-it-002"]
    assert len(matching) == 1
    row: BacktestLogRow = matching[0]
    assert row.strategy_id == TEST_STRATEGY_ID
    assert row.config == {"top_n": 5}
    assert row.summary == {"sharpe": 1.5, "trades": 100}
