"""Unit tests for pipeline hook functions with mocked adapters."""

from __future__ import annotations

import logging
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

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


def _make_pg() -> AsyncMock:
    """Return an ``AsyncMock`` spec'd to ``PostgresAdapter``."""
    pg = AsyncMock()
    pg.write_equity_curve = AsyncMock(return_value=10)
    pg.write_trade_history = AsyncMock(return_value=3)
    pg.write_backtest_log = AsyncMock()
    return pg


def _make_mongo() -> AsyncMock:
    """Return an ``AsyncMock`` spec'd to ``MongoAdapter``."""
    mg = AsyncMock()
    mg.write_backtest_result = AsyncMock()
    mg.write_signal_snapshot = AsyncMock()
    mg.write_model_params = AsyncMock()
    return mg


def _make_gateway() -> AsyncMock:
    """Return an ``AsyncMock`` spec'd to ``GatewayAdapter``."""
    gw = AsyncMock()
    gw.write_daily_performance = AsyncMock()
    gw.write_portfolio_snapshot = AsyncMock()
    return gw


def _make_manager(
    postgres: AsyncMock | None = None,
    mongo: AsyncMock | None = None,
    gateway: AsyncMock | None = None,
) -> AdapterManager:
    """Return ``AdapterManager`` with the given mocked adapters."""
    return AdapterManager(postgres=postgres, mongo=mongo, gateway=gateway)


def _make_synthetic_prices() -> pd.DataFrame:
    """5 symbols x 10 trading days of synthetic close prices, tz-aware UTC."""
    dates: pd.DatetimeIndex = pd.date_range("2026-05-01", periods=10, freq="B", tz="UTC")
    symbols: list[str] = ["A", "B", "C", "D", "E"]
    data: dict[str, list[float]] = {
        s: [100.0 + i * 0.5 + j * 0.1 for i in range(10)] for j, s in enumerate(symbols)
    }
    return pd.DataFrame(data, index=dates)


def _make_synthetic_features() -> pd.DataFrame:
    """3 symbols x 2 dates feature panel with multi-index (date, symbol)."""
    rows: list[dict[str, object]] = []
    for week in (1, 2):
        dt = pd.Timestamp(f"2026-05-{week * 7:02d}", tz="UTC")
        for j, sym in enumerate(["A", "B", "C"]):
            rows.append(
                {
                    "date": dt,
                    "symbol": sym,
                    "momentum_12m": 0.15 - j * 0.05,
                    "volatility_12m": 0.20 + j * 0.02,
                }
            )
    return pd.DataFrame(rows)


def _make_synthetic_backtest_result() -> BacktestResult:
    """Construct a ``BacktestResult`` with synthetic data for testing hooks."""
    config: BacktestConfig = BacktestConfig(formation_months=12, top_quantile=0.2)
    holding: MonthlyHoldingRecord = MonthlyHoldingRecord(symbol="A", weight=0.5, return_pct=0.02)
    period: MonthlyPeriodReport = MonthlyPeriodReport(
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
        positions={"2026-01-31": ["A", "B"], "2026-02-28": ["B", "C"]},
        turnover={"2026-01-31": 0.3, "2026-02-28": 0.2},
        metrics={"cagr": 0.15, "sharpe": 1.2, "max_drawdown": -0.08},
        monthly_report=MonthlyRebalanceReport(periods=[period]),
    )


def _make_store(
    prices: pd.DataFrame | None = None,
    features: pd.DataFrame | None = None,
) -> MagicMock:
    """Return a ``MagicMock(spec=ParquetStore)`` with load side-effects."""
    store: MagicMock = MagicMock(spec=ParquetStore)

    def _load_side_effect(key: str) -> pd.DataFrame:
        if key == "prices_latest" and prices is not None:
            return prices
        if key == "features_latest" and features is not None:
            return features
        raise KeyError(key)

    store.load.side_effect = _load_side_effect
    return store


# ---------------------------------------------------------------------------
# Post-refresh hook tests
# ---------------------------------------------------------------------------


class TestPostRefreshHook:
    """Tests for ``run_post_refresh_hook``."""

    @pytest.mark.asyncio
    async def test_calls_all_four_writes_when_all_adapters_live(self) -> None:
        pg = _make_pg()
        mongo = _make_mongo()
        gw = _make_gateway()
        manager = _make_manager(postgres=pg, mongo=mongo, gateway=gw)
        prices = _make_synthetic_prices()
        features = _make_synthetic_features()
        store = _make_store(prices=prices, features=features)

        summary = {"symbols_fetched": 5, "failures": 0, "duration_seconds": 1.5}
        await run_post_refresh_hook(manager, store, summary=summary)

        pg.write_equity_curve.assert_called_once()
        call_args = pg.write_equity_curve.call_args
        assert call_args[0][0] == "csm-set"
        assert len(call_args[0][1]) > 0  # equity series non-empty

        mongo.write_signal_snapshot.assert_called_once()
        gw.write_daily_performance.assert_called_once()
        gw.write_portfolio_snapshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_writes_when_adapter_slot_is_none(self) -> None:
        """All slots None → no writes attempted, no store loads needed."""
        manager = _make_manager()
        store = _make_store()

        await run_post_refresh_hook(manager, store)

        store.load.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_equity_curve_when_prices_empty(self) -> None:
        pg = _make_pg()
        manager = _make_manager(postgres=pg)
        prices = pd.DataFrame()
        store = _make_store(prices=prices)

        await run_post_refresh_hook(manager, store)

        pg.write_equity_curve.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_equity_curve_when_prices_has_single_row(self) -> None:
        pg = _make_pg()
        manager = _make_manager(postgres=pg)
        ts = pd.Timestamp("2026-05-01", tz="UTC")
        prices = pd.DataFrame({"A": [100.0]}, index=pd.DatetimeIndex([ts]))
        store = _make_store(prices=prices)

        await run_post_refresh_hook(manager, store)

        pg.write_equity_curve.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_store_load_failure_gracefully(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        pg = _make_pg()
        manager = _make_manager(postgres=pg)
        store: MagicMock = MagicMock(spec=ParquetStore)
        store.load.side_effect = OSError("store unavailable")

        with caplog.at_level(logging.WARNING, logger="csm.adapters.hooks"):
            await run_post_refresh_hook(manager, store)

        pg.write_equity_curve.assert_not_called()
        assert any("failed to load prices_latest" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_localizes_tz_naive_index_to_utc(self) -> None:
        pg = _make_pg()
        manager = _make_manager(postgres=pg)
        dates = pd.date_range("2026-05-01", periods=10, freq="B")  # tz-naive
        prices = pd.DataFrame({"A": [100.0 + i * 1.0 for i in range(10)]}, index=dates)
        store = _make_store(prices=prices)

        await run_post_refresh_hook(manager, store)

        pg.write_equity_curve.assert_called_once()
        series = pg.write_equity_curve.call_args[0][1]
        assert series.index.tz is not None
        assert str(series.index.tz) == "UTC"

    @pytest.mark.asyncio
    async def test_converts_non_utc_tz_to_utc(self) -> None:
        pg = _make_pg()
        manager = _make_manager(postgres=pg)
        dates = pd.date_range("2026-05-01", periods=10, freq="B", tz="Asia/Bangkok")
        prices = pd.DataFrame({"A": [100.0 + i * 1.0 for i in range(10)]}, index=dates)
        store = _make_store(prices=prices)

        await run_post_refresh_hook(manager, store)

        pg.write_equity_curve.assert_called_once()
        series = pg.write_equity_curve.call_args[0][1]
        assert str(series.index.tz) == "UTC"

    @pytest.mark.asyncio
    async def test_writes_daily_performance_with_metric_fields(self) -> None:
        gw = _make_gateway()
        manager = _make_manager(gateway=gw)
        prices = _make_synthetic_prices()
        store = _make_store(prices=prices)

        await run_post_refresh_hook(manager, store)

        gw.write_daily_performance.assert_called_once()
        call_kwargs = gw.write_daily_performance.call_args
        strategy_id = call_kwargs[0][0]
        date_arg = call_kwargs[0][1]
        metrics_arg = call_kwargs[0][2]
        assert strategy_id == "csm-set"
        assert isinstance(date_arg, datetime)
        assert "daily_return" in metrics_arg
        assert "cumulative_return" in metrics_arg
        assert "total_value" in metrics_arg
        assert "max_drawdown" in metrics_arg
        assert "sharpe_ratio" in metrics_arg

    @pytest.mark.asyncio
    async def test_writes_portfolio_snapshot_with_allocation(self) -> None:
        gw = _make_gateway()
        manager = _make_manager(gateway=gw)
        prices = _make_synthetic_prices()
        store = _make_store(prices=prices)

        await run_post_refresh_hook(manager, store)

        gw.write_portfolio_snapshot.assert_called_once()
        call_kwargs = gw.write_portfolio_snapshot.call_args
        date_arg = call_kwargs[0][0]
        snapshot_arg = call_kwargs[0][1]
        assert isinstance(date_arg, datetime)
        assert snapshot_arg.get("active_strategies") == 1
        assert "csm-set" in snapshot_arg.get("allocation", {})

    @pytest.mark.asyncio
    async def test_forwards_refresh_summary_to_gateway_metrics(self) -> None:
        gw = _make_gateway()
        manager = _make_manager(gateway=gw)
        prices = _make_synthetic_prices()
        store = _make_store(prices=prices)
        summary = {"symbols_fetched": 42, "failures": 3, "duration_seconds": 12.5}

        await run_post_refresh_hook(manager, store, summary=summary)

        gw.write_daily_performance.assert_called_once()
        metrics_arg = gw.write_daily_performance.call_args[0][2]
        assert metrics_arg.get("symbols_fetched") == 42
        assert metrics_arg.get("failures") == 3
        assert metrics_arg.get("duration_seconds") == 12.5


# ---------------------------------------------------------------------------
# Post-backtest hook tests
# ---------------------------------------------------------------------------


class TestPostBacktestHook:
    """Tests for ``run_post_backtest_hook``."""

    @pytest.mark.asyncio
    async def test_calls_all_three_writes_when_adapters_live(self) -> None:
        pg = _make_pg()
        mongo = _make_mongo()
        manager = _make_manager(postgres=pg, mongo=mongo)
        config: BacktestConfig = BacktestConfig()
        result: BacktestResult = _make_synthetic_backtest_result()
        run_id: str = "test-run-001"

        await run_post_backtest_hook(manager, run_id, "csm-set", config, result)

        pg.write_backtest_log.assert_called_once()
        assert pg.write_backtest_log.call_args[1]["run_id"] == run_id
        assert pg.write_backtest_log.call_args[1]["strategy_id"] == "csm-set"

        mongo.write_backtest_result.assert_called_once()
        mongo.write_model_params.assert_called_once()

    @pytest.mark.asyncio
    async def test_result_doc_contains_expected_fields(self) -> None:
        mongo = _make_mongo()
        manager = _make_manager(mongo=mongo)
        config: BacktestConfig = BacktestConfig()
        result: BacktestResult = _make_synthetic_backtest_result()
        run_id: str = "test-run-002"

        await run_post_backtest_hook(manager, run_id, "csm-set", config, result)

        mongo.write_backtest_result.assert_called_once()
        doc = mongo.write_backtest_result.call_args[0][0]
        assert doc["run_id"] == run_id
        assert doc["strategy_id"] == "csm-set"
        assert "created_at" in doc
        assert "config" in doc
        assert "metrics" in doc
        assert "equity_curve" in doc
        assert "positions" in doc
        assert "turnover" in doc
        assert "annual_returns" in doc
        assert "trades" in doc
        assert isinstance(doc["trades"], list)

    @pytest.mark.asyncio
    async def test_trades_extracted_from_monthly_report(self) -> None:
        mongo = _make_mongo()
        manager = _make_manager(mongo=mongo)
        config: BacktestConfig = BacktestConfig()
        result: BacktestResult = _make_synthetic_backtest_result()

        await run_post_backtest_hook(manager, "test-run-003", "csm-set", config, result)

        doc = mongo.write_backtest_result.call_args[0][0]
        assert len(doc["trades"]) == 1
        trade = doc["trades"][0]
        assert trade["symbol"] == "A"
        assert trade["weight"] == 0.5
        assert trade["return_pct"] == 0.02
        assert trade["period_end"] == "2026-05-31"

    @pytest.mark.asyncio
    async def test_skips_writes_when_adapter_slot_is_none(self) -> None:
        manager = _make_manager()
        config: BacktestConfig = BacktestConfig()
        result: BacktestResult = _make_synthetic_backtest_result()

        await run_post_backtest_hook(manager, "test-run-004", "csm-set", config, result)

        # No error raised — graceful skip

    @pytest.mark.asyncio
    async def test_passes_config_and_summary_to_backtest_log(self) -> None:
        pg = _make_pg()
        manager = _make_manager(postgres=pg)
        config: BacktestConfig = BacktestConfig(formation_months=6)
        result: BacktestResult = _make_synthetic_backtest_result()

        await run_post_backtest_hook(manager, "test-run-005", "csm-set", config, result)

        pg.write_backtest_log.assert_called_once()
        config_arg = pg.write_backtest_log.call_args[1]["config"]
        summary_arg = pg.write_backtest_log.call_args[1]["summary"]
        assert config_arg["formation_months"] == 6
        assert "cagr" in summary_arg
        assert "generated_at" in summary_arg

    @pytest.mark.asyncio
    async def test_model_params_uses_timestamp_version(self) -> None:
        mongo = _make_mongo()
        manager = _make_manager(mongo=mongo)
        config: BacktestConfig = BacktestConfig()
        result: BacktestResult = _make_synthetic_backtest_result()

        await run_post_backtest_hook(manager, "test-run-006", "csm-set", config, result)

        mongo.write_model_params.assert_called_once()
        version = mongo.write_model_params.call_args[0][1]
        # Version format: YYYYMMDD-HHMMSS
        assert len(version) == 15
        assert "-" in version


# ---------------------------------------------------------------------------
# Post-rebalance hook tests
# ---------------------------------------------------------------------------


class TestPostRebalanceHook:
    """Tests for ``run_post_rebalance_hook``."""

    @pytest.mark.asyncio
    async def test_calls_write_trade_history(self) -> None:
        pg = _make_pg()
        manager = _make_manager(postgres=pg)
        trades: pd.DataFrame = pd.DataFrame(
            {
                "time": [pd.Timestamp("2026-05-07", tz="UTC")] * 2,
                "symbol": ["A", "B"],
                "side": ["BUY", "SELL"],
                "quantity": [100.0, 50.0],
                "price": [10.5, 20.0],
                "commission": [1.0, 1.0],
            }
        )

        await run_post_rebalance_hook(manager, "csm-set", trades)

        pg.write_trade_history.assert_called_once_with("csm-set", trades)

    @pytest.mark.asyncio
    async def test_skips_when_postgres_is_none(self) -> None:
        manager = _make_manager()
        trades: pd.DataFrame = pd.DataFrame(
            columns=["time", "symbol", "side", "quantity", "price", "commission"]
        )

        await run_post_rebalance_hook(manager, "csm-set", trades)

        # No error raised

    @pytest.mark.asyncio
    async def test_logs_warning_on_write_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        pg = _make_pg()
        pg.write_trade_history.side_effect = RuntimeError("pool closed")
        manager = _make_manager(postgres=pg)
        trades: pd.DataFrame = pd.DataFrame(
            {
                "time": [pd.Timestamp("2026-05-07", tz="UTC")],
                "symbol": ["A"],
                "side": ["BUY"],
                "quantity": [100.0],
                "price": [10.5],
                "commission": [1.0],
            }
        )

        with caplog.at_level(logging.WARNING, logger="csm.adapters.hooks"):
            await run_post_rebalance_hook(manager, "csm-set", trades)

        assert any("write_trade_history failed" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Error isolation tests
# ---------------------------------------------------------------------------


class TestErrorIsolation:
    """Tests verifying one adapter failure never blocks others."""

    @pytest.mark.asyncio
    async def test_postgres_failure_does_not_block_mongo_and_gateway(self) -> None:
        pg = _make_pg()
        pg.write_equity_curve.side_effect = RuntimeError("postgres down")
        mongo = _make_mongo()
        gw = _make_gateway()
        manager = _make_manager(postgres=pg, mongo=mongo, gateway=gw)
        prices = _make_synthetic_prices()
        features = _make_synthetic_features()
        store = _make_store(prices=prices, features=features)

        await run_post_refresh_hook(manager, store)

        # Postgres failed, but others should have been called
        pg.write_equity_curve.assert_called_once()
        mongo.write_signal_snapshot.assert_called_once()
        gw.write_daily_performance.assert_called_once()
        gw.write_portfolio_snapshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_mongo_failure_does_not_block_postgres(self) -> None:
        pg = _make_pg()
        mongo = _make_mongo()
        mongo.write_backtest_result.side_effect = RuntimeError("mongo down")
        manager = _make_manager(postgres=pg, mongo=mongo)
        config: BacktestConfig = BacktestConfig()
        result: BacktestResult = _make_synthetic_backtest_result()

        await run_post_backtest_hook(manager, "test-run-err", "csm-set", config, result)

        pg.write_backtest_log.assert_called_once()  # still called
        mongo.write_model_params.assert_called_once()  # different method, still called

    @pytest.mark.asyncio
    async def test_logs_warnings_for_each_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        pg = _make_pg()
        pg.write_equity_curve.side_effect = RuntimeError("pg down")
        mongo = _make_mongo()
        mongo.write_signal_snapshot.side_effect = RuntimeError("mongo down")
        gw = _make_gateway()
        gw.write_daily_performance.side_effect = RuntimeError("gw down")
        manager = _make_manager(postgres=pg, mongo=mongo, gateway=gw)
        prices = _make_synthetic_prices()
        features = _make_synthetic_features()
        store = _make_store(prices=prices, features=features)

        with caplog.at_level(logging.WARNING, logger="csm.adapters.hooks"):
            await run_post_refresh_hook(manager, store)

        warnings = [rec.message for rec in caplog.records]
        assert any("write_equity_curve failed" in m for m in warnings)
        assert any("write_signal_snapshot failed" in m for m in warnings)
        assert any("write_daily_performance failed" in m for m in warnings)
        # portfolio_snapshot is separate — should still be called (even if it also fails)
        gw.write_portfolio_snapshot.assert_called_once()
