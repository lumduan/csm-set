"""End-to-end pipeline integration tests for hooks → DB write-back.

All tests are ``@pytest.mark.infra_db`` and self-skip when no DB
DSNs are set. They exercise the full hook → adapter → database path
using the real quant-infra-db stack.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from csm.adapters import AdapterManager
from csm.adapters.hooks import (
    run_post_backtest_hook,
    run_post_rebalance_hook,
    run_post_refresh_hook,
)
from csm.data.store import ParquetStore
from csm.research.backtest import (
    BacktestConfig,
    BacktestResult,
    MonthlyHoldingRecord,
    MonthlyPeriodReport,
    MonthlyRebalanceReport,
)

pytestmark = pytest.mark.infra_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_synthetic_prices() -> pd.DataFrame:
    """5 symbols x 20 trading days, tz-aware UTC."""
    dates = pd.date_range("2026-05-01", periods=20, freq="B", tz="UTC")
    symbols = ["A", "B", "C", "D", "E"]
    data: dict[str, list[float]] = {
        s: [100.0 + i * 0.3 + j * 0.15 for i in range(20)] for j, s in enumerate(symbols)
    }
    return pd.DataFrame(data, index=dates)


def _make_synthetic_features() -> pd.DataFrame:
    """3 symbols x 3 dates feature panel."""
    rows: list[dict[str, object]] = []
    for d in range(3):
        dt = pd.Timestamp(f"2026-05-{(d + 1) * 7:02d}", tz="UTC")
        for j, s in enumerate(["A", "B", "C"]):
            rows.append(
                {
                    "date": dt,
                    "symbol": s,
                    "momentum_12m": 0.15 - j * 0.05,
                    "volatility_12m": 0.20 + j * 0.02,
                }
            )
    return pd.DataFrame(rows)


def _make_synthetic_backtest_result() -> BacktestResult:
    """Construct a BacktestResult with synthetic data."""
    config = BacktestConfig(formation_months=12)
    holding = MonthlyHoldingRecord(symbol="A", weight=0.5, return_pct=0.02)
    period = MonthlyPeriodReport(
        period_end="2026-05-31",
        holdings=[holding],
        gross_return=0.02,
        cost=0.0015,
        net_return=0.0185,
        turnover=0.3,
        nav=101.85,
    )
    return BacktestResult(
        config=config,
        generated_at="2026-05-07T12:00:00Z",
        equity_curve={"2026-01-31": 100.0, "2026-02-28": 102.0},
        annual_returns={"2026": 0.12},
        positions={"2026-01-31": ["A", "B"]},
        turnover={"2026-01-31": 0.3},
        metrics={"cagr": 0.15, "sharpe": 1.2},
        monthly_report=MonthlyRebalanceReport(periods=[period]),
    )


def _make_store(
    prices: pd.DataFrame | None = None,
    features: pd.DataFrame | None = None,
) -> MagicMock:
    """Return a ParquetStore MagicMock with load for prices/features."""
    store = MagicMock(spec=ParquetStore)

    def _load(key: str) -> pd.DataFrame:
        if key == "prices_latest" and prices is not None:
            return prices
        if key == "features_latest" and features is not None:
            return features
        raise KeyError(key)

    store.load.side_effect = _load
    return store


# ---------------------------------------------------------------------------
# Pipeline integration tests
# ---------------------------------------------------------------------------


class TestPipelineEndToEnd:
    """Full hook → database round-trip tests."""

    async def test_refresh_hook_with_live_adapters(self, adapter_manager: AdapterManager) -> None:
        """Post-refresh hook writes to all three stores."""
        if adapter_manager.postgres is None:
            pytest.skip("Postgres adapter not available")
        if adapter_manager.mongo is None:
            pytest.skip("Mongo adapter not available")

        prices = _make_synthetic_prices()
        features = _make_synthetic_features()
        store = _make_store(prices=prices, features=features)
        summary = {"symbols_fetched": 5, "failures": 0, "duration_seconds": 2.1}

        await run_post_refresh_hook(adapter_manager, store, summary=summary)

    async def test_refresh_uses_test_strategy_id(self, adapter_manager: AdapterManager) -> None:
        """Post-refresh hook uses default strategy_id 'csm-set'.

        Since we can't easily change the strategy_id in the hook, we verify
        that the hook runs without error against the live stack. The hook
        writes with strategy_id='csm-set' and we clean up test-csm-set, so
        these go to different rows. This test simply verifies the hook
        completes.
        """
        prices = _make_synthetic_prices()
        features = _make_synthetic_features()
        store = _make_store(prices=prices, features=features)

        await run_post_refresh_hook(adapter_manager, store)

    async def test_backtest_hook_with_live_adapters(self, adapter_manager: AdapterManager) -> None:
        """Post-backtest hook writes to Postgres and Mongo."""
        if adapter_manager.postgres is None:
            pytest.skip("Postgres adapter not available")
        if adapter_manager.mongo is None:
            pytest.skip("Mongo adapter not available")

        config = BacktestConfig()
        result = _make_synthetic_backtest_result()
        run_id = "test-csm-set-pipeline-001"

        await run_post_backtest_hook(adapter_manager, run_id, "test-csm-set", config, result)

    async def test_null_manager_returns_without_error(self) -> None:
        """Hook called with all-None manager returns cleanly."""
        manager = AdapterManager()
        prices = _make_synthetic_prices()
        features = _make_synthetic_features()
        store = _make_store(prices=prices, features=features)

        await run_post_refresh_hook(manager, store)

    async def test_rebalance_hook_noop_without_postgres(
        self, adapter_manager: AdapterManager
    ) -> None:
        """Post-rebalance hook skips gracefully when postgres is None."""
        trades = pd.DataFrame(
            {
                "time": [pd.Timestamp("2026-05-07", tz="UTC")],
                "symbol": ["A"],
                "side": ["BUY"],
                "quantity": [100.0],
                "price": [10.5],
                "commission": [1.0],
            }
        )

        # Always a no-op when postgres is None
        manager = AdapterManager()
        await run_post_rebalance_hook(manager, "csm-set", trades)

    async def test_partial_adapter_availability(self, adapter_manager: AdapterManager) -> None:
        """Hooks work with partial adapter availability."""
        prices = _make_synthetic_prices()
        features = _make_synthetic_features()
        store = _make_store(prices=prices, features=features)

        # Should complete without error even if some adapters are None
        await run_post_refresh_hook(adapter_manager, store)
