"""Integration tests for ``GatewayAdapter`` reads against the real ``db_gateway``.

Marked ``@pytest.mark.infra_db`` — skipped by default, selected only when
``CSM_DB_GATEWAY_DSN`` is set and the ``infra_db`` marker is included.

``GatewayAdapter`` is **read-only**: the write path moved to the HTTP ingestion
contract (``POST /api/v1/ingest/daily-report``) in commit ``0486e5d``
(2026-05-22). These tests therefore seed through the raw-SQL helpers in
:mod:`tests.integration.adapters.conftest` and assert on the **read** path,
which is what csm-set still owns. Idempotency of the write is the gateway
service's contract and is tested there, not here.

Every seeded timestamp is **now-relative**. ``read_daily_performance`` and
``read_portfolio_snapshots`` filter on a rolling window of calendar days
(changed in ``26eebbe``), so a fixed historical base silently returns nothing.
``portfolio_snapshot`` is additionally cross-strategy, so its assertions filter
to rows this suite seeded rather than assuming an empty table.
"""

from __future__ import annotations

import pytest

from csm.adapters.gateway import GatewayAdapter
from csm.adapters.models import DailyPerformanceRow, PortfolioSnapshotRow

from .conftest import (
    TEST_STRATEGY_ID,
    seed_daily_performance,
    seed_portfolio_snapshot,
    snapshot_time_utc,
)

pytestmark = pytest.mark.infra_db


def _mine(rows: list[PortfolioSnapshotRow]) -> list[PortfolioSnapshotRow]:
    """Filter cross-strategy snapshot rows down to the ones this suite seeded."""
    return [r for r in rows if TEST_STRATEGY_ID in r.allocation]


class TestReadDailyPerformance:
    async def test_read_round_trip(self, gateway_adapter: GatewayAdapter) -> None:
        gw = gateway_adapter
        metrics: dict[str, object] = {
            "daily_return": 0.012,
            "cumulative_return": 0.15,
            "total_value": 1_000_000.0,
            "cash_balance": 50_000.0,
            "max_drawdown": -0.05,
            "sharpe_ratio": 1.42,
        }
        await seed_daily_performance(gw, snapshot_time_utc(0), metrics)

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

    async def test_read_respects_days_window(self, gateway_adapter: GatewayAdapter) -> None:
        """``days`` is a calendar-day window, so only the recent rows come back."""
        gw = gateway_adapter
        for days_ago in range(5):
            await seed_daily_performance(
                gw,
                snapshot_time_utc(days_ago),
                {"daily_return": days_ago / 100.0, "sharpe_ratio": 1.0},
            )

        rows = await gw.read_daily_performance(TEST_STRATEGY_ID, days=3)
        assert len(rows) == 3

    async def test_read_excludes_rows_outside_the_window(
        self, gateway_adapter: GatewayAdapter
    ) -> None:
        """A row older than ``days`` must not be returned.

        This is the half of the window contract that had no coverage: the old
        ``LIMIT``-based read returned the N most recent rows regardless of age, so
        a test seeding old data still passed. Under a date window it must not.
        """
        gw = gateway_adapter
        await seed_daily_performance(gw, snapshot_time_utc(0), {"daily_return": 0.01})
        await seed_daily_performance(gw, snapshot_time_utc(30), {"daily_return": 0.99})

        rows = await gw.read_daily_performance(TEST_STRATEGY_ID, days=7)
        assert len(rows) == 1
        assert rows[0].daily_return == 0.01

        wide = await gw.read_daily_performance(TEST_STRATEGY_ID, days=60)
        assert len(wide) == 2

    async def test_read_ascending_time_order(self, gateway_adapter: GatewayAdapter) -> None:
        gw = gateway_adapter
        for days_ago in (2, 0, 1):  # seeded out of order on purpose
            await seed_daily_performance(
                gw, snapshot_time_utc(days_ago), {"daily_return": 0.01, "sharpe_ratio": 1.0}
            )

        rows = await gw.read_daily_performance(TEST_STRATEGY_ID, days=5)
        assert len(rows) == 3
        assert rows[0].time < rows[1].time < rows[2].time


class TestReadPortfolioSnapshots:
    async def test_read_round_trip(self, gateway_adapter: GatewayAdapter) -> None:
        gw = gateway_adapter
        await seed_portfolio_snapshot(
            gw,
            snapshot_time_utc(0),
            {
                "total_portfolio": 1_500_000.0,
                "weighted_return": 0.008,
                "combined_drawdown": -0.03,
                "active_strategies": 1,
                "allocation": {TEST_STRATEGY_ID: 1.0},
            },
        )

        rows = _mine(await gw.read_portfolio_snapshots(days=1))
        assert len(rows) == 1
        row = rows[0]
        assert isinstance(row, PortfolioSnapshotRow)
        assert row.total_portfolio == 1_500_000.0
        assert row.weighted_return == 0.008
        assert row.combined_drawdown == -0.03
        assert row.active_strategies == 1
        assert row.allocation == {TEST_STRATEGY_ID: 1.0}

    async def test_read_respects_days_window(self, gateway_adapter: GatewayAdapter) -> None:
        gw = gateway_adapter
        for days_ago in range(5):
            await seed_portfolio_snapshot(
                gw,
                snapshot_time_utc(days_ago),
                {"total_portfolio": 1_000_000.0 + days_ago * 10_000},
            )

        rows = _mine(await gw.read_portfolio_snapshots(days=3))
        assert len(rows) == 3

    async def test_read_ascending_time_order(self, gateway_adapter: GatewayAdapter) -> None:
        gw = gateway_adapter
        for days_ago in (2, 0, 1):  # seeded out of order on purpose
            await seed_portfolio_snapshot(
                gw, snapshot_time_utc(days_ago), {"total_portfolio": 1_000_000.0}
            )

        rows = _mine(await gw.read_portfolio_snapshots(days=5))
        assert len(rows) == 3
        assert rows[0].time < rows[1].time < rows[2].time
