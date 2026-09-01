"""Unit tests for pipeline hook functions with mocked adapters."""

from __future__ import annotations

import logging
import textwrap
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from csm.adapters import AdapterManager
from csm.adapters.hooks import (
    _reconstruct_live_equity,
    run_post_backtest_hook,
    run_post_rebalance_hook,
    run_post_refresh_hook,
)
from csm.adapters.payload import _series_to_equity_curve
from csm.data.store import ParquetStore
from csm.live import LivePortfolioConfig, LivePosition
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


def _make_gateway_client() -> AsyncMock:
    """Return an ``AsyncMock`` spec'd to ``GatewayClient``."""
    gc = AsyncMock()
    gc.post_daily_report = AsyncMock()
    return gc


def _make_manager(
    postgres: AsyncMock | None = None,
    mongo: AsyncMock | None = None,
    gateway_client: AsyncMock | None = None,
) -> AdapterManager:
    """Return ``AdapterManager`` with the given mocked adapters."""
    return AdapterManager(postgres=postgres, mongo=mongo, gateway_client=gateway_client)


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


def _write_live_portfolio_yaml(tmp_path: Path) -> Path:
    """Write a synthetic live-portfolio config aligned with ``_make_synthetic_prices``.

    Uses bare symbol names (``A``, ``B``…) so the loader prepends ``SET:`` and
    looks them up in the corresponding parquet columns — which the synthetic
    prices fixture matches when columns are renamed to the ``SET:`` form.
    """
    yaml_text: str = textwrap.dedent(
        """
        strategy_id: csm-set
        entry_date: "2026-05-01"
        starting_nav: 1000.0
        cash: 100.0
        positions:
          - {symbol: "SET:A", shares: 1.0, avg_cost: 100.0}
          - {symbol: "SET:B", shares: 1.0, avg_cost: 100.0}
          - {symbol: "SET:C", shares: 1.0, avg_cost: 100.0}
          - {symbol: "SET:D", shares: 1.0, avg_cost: 100.0}
          - {symbol: "SET:E", shares: 1.0, avg_cost: 100.0}
        """
    ).strip()
    path: Path = tmp_path / "live_portfolio.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    return path


def _make_synthetic_prices_set_columns() -> pd.DataFrame:
    """Same shape as ``_make_synthetic_prices`` but columns are ``SET:`` prefixed."""
    df: pd.DataFrame = _make_synthetic_prices()
    df.columns = [f"SET:{c}" for c in df.columns]
    return df


def _prices_ending(days_ago: int = 0, *, periods: int = 10) -> pd.DataFrame:
    """``SET:``-prefixed price panel whose **last bar** is ``days_ago`` days back.

    The hook now refuses to POST a daily report unless the latest bar is *today*
    (Bangkok), so any test that expects a POST needs a panel anchored to the
    current date rather than the fixed 2026-05 base ``_make_synthetic_prices``
    uses. Bars are stamped 09:55 ``Asia/Bangkok`` to match production.

    Args:
        days_ago: 0 → the last bar is today (POST expected); 1 → yesterday
            (POST must be skipped, the market-closure case).
        periods: Number of consecutive daily bars to emit.
    """
    last_day = (datetime.now(ZoneInfo("Asia/Bangkok")) - timedelta(days=days_ago)).date()
    last_bar = pd.Timestamp(
        datetime.combine(last_day, time(9, 55), tzinfo=ZoneInfo("Asia/Bangkok"))
    )
    index = pd.DatetimeIndex(
        [last_bar - pd.Timedelta(days=periods - 1 - i) for i in range(periods)]
    )
    symbols: list[str] = ["A", "B", "C", "D", "E"]
    data: dict[str, list[float]] = {
        f"SET:{s}": [100.0 + i * 0.5 + j * 0.1 for i in range(periods)]
        for j, s in enumerate(symbols)
    }
    return pd.DataFrame(data, index=index)


def _live_portfolio_yaml_from(tmp_path: Path, prices: pd.DataFrame) -> Path:
    """Write a live-portfolio config whose ``entry_date`` matches ``prices``.

    ``_write_live_portfolio_yaml`` hard-codes ``2026-05-01``, which sits outside a
    now-relative panel and would leave the repriced window empty.
    """
    entry: str = prices.index[0].date().isoformat()
    yaml_text: str = textwrap.dedent(
        f"""
        strategy_id: csm-set
        entry_date: "{entry}"
        starting_nav: 1000.0
        cash: 100.0
        positions:
          - {{symbol: "SET:A", shares: 1.0, avg_cost: 100.0}}
          - {{symbol: "SET:B", shares: 1.0, avg_cost: 100.0}}
          - {{symbol: "SET:C", shares: 1.0, avg_cost: 100.0}}
          - {{symbol: "SET:D", shares: 1.0, avg_cost: 100.0}}
          - {{symbol: "SET:E", shares: 1.0, avg_cost: 100.0}}
        """
    ).strip()
    path: Path = tmp_path / "live_portfolio.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Post-refresh hook tests
# ---------------------------------------------------------------------------


class TestPostRefreshHook:
    """Tests for ``run_post_refresh_hook``."""

    @pytest.mark.asyncio
    async def test_calls_all_three_writes_when_all_adapters_live(self, tmp_path: Path) -> None:
        pg = _make_pg()
        mongo = _make_mongo()
        gc = _make_gateway_client()
        manager = _make_manager(postgres=pg, mongo=mongo, gateway_client=gc)
        prices = _prices_ending(0)
        features = _make_synthetic_features()
        store = _make_store(prices=prices, features=features)
        live_path = _live_portfolio_yaml_from(tmp_path, prices)

        summary = {"symbols_fetched": 5, "failures": 0, "duration_seconds": 1.5}
        await run_post_refresh_hook(manager, store, summary=summary, live_portfolio_path=live_path)

        pg.write_equity_curve.assert_called_once()
        call_args = pg.write_equity_curve.call_args
        assert call_args[0][0] == "csm-set"
        assert len(call_args[0][1]) > 0  # equity series non-empty

        mongo.write_signal_snapshot.assert_called_once()
        gc.post_daily_report.assert_called_once()

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
    async def test_localizes_tz_naive_index_to_utc(self, tmp_path: Path) -> None:
        pg = _make_pg()
        manager = _make_manager(postgres=pg)
        dates = pd.date_range("2026-05-01", periods=10, freq="B")  # tz-naive
        symbols = ["SET:A", "SET:B", "SET:C", "SET:D", "SET:E"]
        prices = pd.DataFrame(
            {s: [100.0 + i * 1.0 + j * 0.1 for i in range(10)] for j, s in enumerate(symbols)},
            index=dates,
        )
        store = _make_store(prices=prices)
        live_path = _write_live_portfolio_yaml(tmp_path)

        await run_post_refresh_hook(manager, store, live_portfolio_path=live_path)

        pg.write_equity_curve.assert_called_once()
        series = pg.write_equity_curve.call_args[0][1]
        assert series.index.tz is not None
        assert str(series.index.tz) == "UTC"

    @pytest.mark.asyncio
    async def test_converts_non_utc_tz_to_utc(self, tmp_path: Path) -> None:
        pg = _make_pg()
        manager = _make_manager(postgres=pg)
        dates = pd.date_range("2026-05-01", periods=10, freq="B", tz="Asia/Bangkok")
        symbols = ["SET:A", "SET:B", "SET:C", "SET:D", "SET:E"]
        prices = pd.DataFrame(
            {s: [100.0 + i * 1.0 + j * 0.1 for i in range(10)] for j, s in enumerate(symbols)},
            index=dates,
        )
        store = _make_store(prices=prices)
        live_path = _write_live_portfolio_yaml(tmp_path)

        await run_post_refresh_hook(manager, store, live_portfolio_path=live_path)

        pg.write_equity_curve.assert_called_once()
        series = pg.write_equity_curve.call_args[0][1]
        assert str(series.index.tz) == "UTC"

    @pytest.mark.asyncio
    async def test_equity_index_is_date_normalized(self, tmp_path: Path) -> None:
        """equity_curve is one row per day, so the series must be keyed by date."""
        pg = _make_pg()
        manager = _make_manager(postgres=pg)
        # 09:55 BKK — the real market-data bar time-of-day as of 2026-07-31.
        dates = pd.date_range("2026-05-01 09:55", periods=10, freq="B", tz="Asia/Bangkok")
        symbols = ["SET:A", "SET:B", "SET:C", "SET:D", "SET:E"]
        prices = pd.DataFrame(
            {s: [100.0 + i * 1.0 + j * 0.1 for i in range(10)] for j, s in enumerate(symbols)},
            index=dates,
        )
        store = _make_store(prices=prices)
        live_path = _write_live_portfolio_yaml(tmp_path)

        await run_post_refresh_hook(manager, store, live_portfolio_path=live_path)

        series = pg.write_equity_curve.call_args[0][1]
        assert str(series.index.tz) == "UTC"
        assert (series.index == series.index.normalize()).all(), (
            f"index carries a time-of-day: {sorted({t.strftime('%H:%M') for t in series.index})}"
        )
        # one key per calendar day
        assert len(series.index) == len({t.date() for t in series.index})

    @pytest.mark.asyncio
    async def test_bar_time_of_day_change_does_not_re_key_the_series(self, tmp_path: Path) -> None:
        """Regression: the upsert target is (time, strategy_id), so a vendor-side change in
        the price bar's time-of-day must NOT produce new keys.

        Before this was fixed, tvkit moved the daily bar 09:00 -> 10:00 -> 09:55 BKK and each
        move made the daily refresh INSERT a fresh copy of the whole [entry_date, today]
        window instead of updating it in place — 97 rows across 60 dates.
        """
        symbols = ["SET:A", "SET:B", "SET:C", "SET:D", "SET:E"]
        live_path = _write_live_portfolio_yaml(tmp_path)

        def _prices_at(time_of_day: str) -> pd.DataFrame:
            dates = pd.date_range(
                f"2026-05-01 {time_of_day}", periods=10, freq="B", tz="Asia/Bangkok"
            )
            return pd.DataFrame(
                {s: [100.0 + i * 1.0 + j * 0.1 for i in range(10)] for j, s in enumerate(symbols)},
                index=dates,
            )

        captured: list[pd.Series] = []
        for tod in ("09:00", "09:55"):
            pg = _make_pg()
            manager = _make_manager(postgres=pg)
            await run_post_refresh_hook(
                manager, _make_store(prices=_prices_at(tod)), live_portfolio_path=live_path
            )
            captured.append(pg.write_equity_curve.call_args[0][1])

        first, second = captured
        assert first.index.equals(second.index), (
            "a bar time-of-day change re-keyed the series — the next refresh would insert "
            "duplicates instead of upserting"
        )
        pd.testing.assert_series_equal(first, second)

    @pytest.mark.asyncio
    async def test_normalization_does_not_change_the_gateway_payload(self, tmp_path: Path) -> None:
        """_series_to_equity_curve already emits date-only keys, so the wire format is
        unaffected by normalizing upstream."""
        idx = pd.date_range("2026-05-01 02:55", periods=5, freq="B", tz="UTC")
        raw = pd.Series([1000.0 + i for i in range(5)], index=idx, name="equity")
        normalized = pd.Series(raw.to_numpy(), index=idx.normalize(), name="equity")

        assert _series_to_equity_curve(raw) == _series_to_equity_curve(normalized)

    @pytest.mark.asyncio
    async def test_posts_daily_report_with_contract_shape(self, tmp_path: Path) -> None:
        gc = _make_gateway_client()
        manager = _make_manager(gateway_client=gc)
        prices = _prices_ending(0)
        store = _make_store(prices=prices)
        live_path = _live_portfolio_yaml_from(tmp_path, prices)

        await run_post_refresh_hook(manager, store, live_portfolio_path=live_path)

        gc.post_daily_report.assert_called_once()
        payload = gc.post_daily_report.call_args[0][0]
        assert payload["strategy_metadata"]["id"] == "csm-set"
        assert payload["strategy_metadata"]["type"] == "EQUITY_MOMENTUM"
        assert payload["strategy_metadata"]["last_updated"].endswith("+00:00")
        perf = payload["performance_metrics"]
        assert "daily_pnl" in perf
        assert "equity_curve" in perf and len(perf["equity_curve"]) >= 1
        assert "max_drawdown" in perf
        assert "sharpe_ratio" in perf
        exposure = payload["current_exposure"]
        assert "total_value" in exposure
        assert "cash_balance" in exposure
        assert "positions_count" in exposure

    @pytest.mark.asyncio
    async def test_skips_post_when_live_config_missing(self, tmp_path: Path) -> None:
        """Without a live portfolio config the daily-report POST is skipped."""
        gc = _make_gateway_client()
        manager = _make_manager(gateway_client=gc)
        prices = _prices_ending(0)
        store = _make_store(prices=prices)
        missing_path = tmp_path / "does_not_exist.yaml"

        await run_post_refresh_hook(manager, store, live_portfolio_path=missing_path)

        gc.post_daily_report.assert_not_called()

    @pytest.mark.asyncio
    async def test_daily_report_uses_live_portfolio_nav(self, tmp_path: Path) -> None:
        """The posted payload carries the live portfolio NAV, not the synthetic one."""
        gc = _make_gateway_client()
        manager = _make_manager(gateway_client=gc)
        prices = _prices_ending(0)
        store = _make_store(prices=prices)
        live_path = _live_portfolio_yaml_from(tmp_path, prices)

        await run_post_refresh_hook(manager, store, live_portfolio_path=live_path)

        payload = gc.post_daily_report.call_args[0][0]
        # Live NAV = 5 positions x ~latest close + 100 cash; synthetic universe
        # equity is ~100. Anything above 200 confirms the live path was used.
        assert float(payload["current_exposure"]["total_value"]) > 200.0
        assert payload["current_exposure"]["positions_count"] == 5


# ---------------------------------------------------------------------------
# Post-backtest hook tests
# ---------------------------------------------------------------------------


class TestNoFreshBarNoGatewayWrite:
    """The gateway daily report is skipped when the latest bar is not today's.

    Regression cover for the phantom holiday rows: on 2026-06-01, 06-03, 07-28 and
    07-29 SET did not trade, the scheduler fired anyway, and the hook POSTed an exact
    carry-forward of the previous session stamped with the wall clock — 12 rows across
    the three gateway tables. ``equity_curve`` never had the bug because it derives its
    dates from the price panel; these tests pin that the gateway path now does too.
    """

    @pytest.mark.asyncio
    async def test_skips_post_when_latest_bar_is_not_today(self, tmp_path: Path) -> None:
        """The 2026-07-28 scenario: a panel whose last bar is yesterday."""
        gc = _make_gateway_client()
        manager = _make_manager(gateway_client=gc)
        prices = _prices_ending(1)  # market closed today — last bar is yesterday's
        store = _make_store(prices=prices)
        live_path = _live_portfolio_yaml_from(tmp_path, prices)

        await run_post_refresh_hook(
            manager,
            store,
            summary={"symbols_fetched": 5, "failures": 0},
            live_portfolio_path=live_path,
        )

        gc.post_daily_report.assert_not_called()

    @pytest.mark.asyncio
    async def test_posts_when_latest_bar_is_today(self, tmp_path: Path) -> None:
        """Positive control — a guard that only ever skips is as broken as none."""
        gc = _make_gateway_client()
        manager = _make_manager(gateway_client=gc)
        prices = _prices_ending(0)
        store = _make_store(prices=prices)
        live_path = _live_portfolio_yaml_from(tmp_path, prices)

        await run_post_refresh_hook(manager, store, live_portfolio_path=live_path)

        gc.post_daily_report.assert_called_once()

    @pytest.mark.asyncio
    async def test_last_updated_comes_from_the_bar_not_the_clock(self, tmp_path: Path) -> None:
        """The stamp is the bar's date at UTC midnight, matching every stored row.

        Two things are asserted together on purpose. The **date** must come from the
        data (not ``datetime.now()``), and the **time-of-day** must stay 00:00:00 UTC:
        `daily_performance` is uniformly midnight and unique on ``(time, strategy_id)``,
        so posting the raw 09:55 Bangkok bar time would insert a second row per day
        instead of upserting — the mechanism that took ``equity_curve`` to 97 rows
        across 60 dates.
        """
        gc = _make_gateway_client()
        manager = _make_manager(gateway_client=gc)
        prices = _prices_ending(0)
        store = _make_store(prices=prices)
        live_path = _live_portfolio_yaml_from(tmp_path, prices)

        await run_post_refresh_hook(manager, store, live_portfolio_path=live_path)

        payload = gc.post_daily_report.call_args[0][0]
        last_updated = payload["strategy_metadata"]["last_updated"]
        bar_date = prices.index[-1].date().isoformat()
        assert last_updated.startswith(bar_date)
        assert last_updated.endswith("T00:00:00+00:00")

    @pytest.mark.asyncio
    async def test_equity_curve_still_written_when_the_post_is_skipped(
        self, tmp_path: Path
    ) -> None:
        """The fix must not over-reach into the path that never had the bug.

        ``write_equity_curve`` upserts the whole ``[entry_date, today]`` window keyed by
        calendar day, so re-writing it on a closed day is idempotent — it lands on the
        rows already there and adds nothing. Suppressing it would be a behaviour change
        with no defect behind it.
        """
        pg = _make_pg()
        gc = _make_gateway_client()
        manager = _make_manager(postgres=pg, gateway_client=gc)
        prices = _prices_ending(1)
        store = _make_store(prices=prices)
        live_path = _live_portfolio_yaml_from(tmp_path, prices)

        await run_post_refresh_hook(manager, store, live_portfolio_path=live_path)

        gc.post_daily_report.assert_not_called()
        pg.write_equity_curve.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_log_distinguishes_closure_from_fetch_failure(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Both cases skip; the log says which, so the operator can act."""
        prices = _prices_ending(1)
        store = _make_store(prices=prices)
        live_path = _live_portfolio_yaml_from(tmp_path, prices)

        with caplog.at_level(logging.WARNING, logger="csm.adapters.hooks"):
            await run_post_refresh_hook(
                _make_manager(gateway_client=_make_gateway_client()),
                store,
                summary={"symbols_fetched": 5, "failures": 0, "held_symbols_failed": 0},
                live_portfolio_path=live_path,
            )
        assert "consistent with a market closure" in caplog.text

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="csm.adapters.hooks"):
            await run_post_refresh_hook(
                _make_manager(gateway_client=_make_gateway_client()),
                store,
                summary={"symbols_fetched": 3, "failures": 2, "held_symbols_failed": 1},
                live_portfolio_path=live_path,
            )
        assert "likely a DATA problem" in caplog.text


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
    async def test_postgres_failure_does_not_block_mongo_and_gateway(self, tmp_path: Path) -> None:
        pg = _make_pg()
        pg.write_equity_curve.side_effect = RuntimeError("postgres down")
        mongo = _make_mongo()
        gc = _make_gateway_client()
        manager = _make_manager(postgres=pg, mongo=mongo, gateway_client=gc)
        prices = _prices_ending(0)
        features = _make_synthetic_features()
        store = _make_store(prices=prices, features=features)
        live_path = _live_portfolio_yaml_from(tmp_path, prices)

        await run_post_refresh_hook(manager, store, live_portfolio_path=live_path)

        # Postgres failed, but others should have been called
        pg.write_equity_curve.assert_called_once()
        mongo.write_signal_snapshot.assert_called_once()
        gc.post_daily_report.assert_called_once()

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
    async def test_logs_warnings_for_each_failure(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from csm.adapters.gateway_client import GatewayWriteError

        pg = _make_pg()
        pg.write_equity_curve.side_effect = RuntimeError("pg down")
        mongo = _make_mongo()
        mongo.write_signal_snapshot.side_effect = RuntimeError("mongo down")
        gc = _make_gateway_client()
        gc.post_daily_report.side_effect = GatewayWriteError("gateway down")
        manager = _make_manager(postgres=pg, mongo=mongo, gateway_client=gc)
        prices = _prices_ending(0)
        features = _make_synthetic_features()
        store = _make_store(prices=prices, features=features)
        live_path = _live_portfolio_yaml_from(tmp_path, prices)

        with caplog.at_level(logging.WARNING, logger="csm.adapters.hooks"):
            await run_post_refresh_hook(manager, store, live_portfolio_path=live_path)

        warnings = [rec.message for rec in caplog.records]
        assert any("write_equity_curve failed" in m for m in warnings)
        assert any("write_signal_snapshot failed" in m for m in warnings)
        assert any("gateway daily-report POST failed" in m for m in warnings)


# ---------------------------------------------------------------------------
# Regression: the 2026-09-01 dual-bar corruption, equity-reconstruction half.
#
# `_reconstruct_live_equity` normalizes its index to UTC midnight to keep the
# equity_curve upsert at one row per day. That is necessary but NOT sufficient:
# when the vendor emitted two bars for one session, BOTH normalized onto the
# same key and the upsert took the LAST write. On 2026-09-01 that silently
# replaced the banked 2026-08-31 row (1,317,530.70) with a two-symbol
# valuation (303,397.70) — a read defect that became a write defect.
#
# See docs/live-test/events/2026-09-01-dual-bar-nav-corruption.md.
# ---------------------------------------------------------------------------


class TestReconstructLiveEquityDualBar:
    @staticmethod
    def _cfg() -> LivePortfolioConfig:
        return LivePortfolioConfig(
            strategy_id="csm-set",
            entry_date=pd.Timestamp("2026-08-31").date(),
            starting_nav=100.0,
            cash=1.0,
            positions=(
                LivePosition(symbol="A", shares=10.0, avg_cost=1.0),
                LivePosition(symbol="B", shares=100.0, avg_cost=1.0),
            ),
        )

    @staticmethod
    def _dual_bar_prices() -> pd.DataFrame:
        """2026-08-31 complete; 2026-09-01 split across two complementary bars."""
        index: pd.DatetimeIndex = pd.DatetimeIndex(
            [
                pd.Timestamp("2026-08-31 09:55", tz="Asia/Bangkok"),
                pd.Timestamp("2026-09-01 09:55", tz="Asia/Bangkok"),
                pd.Timestamp("2026-09-01 10:00", tz="Asia/Bangkok"),
            ]
        )
        return pd.DataFrame(
            {
                "SET:A": [10.0, 12.0, float("nan")],
                "SET:B": [2.0, float("nan"), 3.0],
            },
            index=index,
        )

    def test_emits_one_row_per_day_with_union_values(self) -> None:
        series: pd.Series = _reconstruct_live_equity(
            live_config=self._cfg(), prices=self._dual_bar_prices()
        )
        assert len(series) == 2
        assert series.index.is_unique, "a duplicate key is what let the upsert overwrite"
        # 08-31: 10*10.0 + 100*2.0 + 1.0 ; 09-01 union: 10*12.0 + 100*3.0 + 1.0
        assert list(series.to_numpy()) == pytest.approx([301.0, 421.0])

    def test_the_earlier_days_banked_value_is_not_overwritten(self) -> None:
        """The precise failure: 2026-08-31 must survive a 2026-09-01 refresh."""
        series: pd.Series = _reconstruct_live_equity(
            live_config=self._cfg(), prices=self._dual_bar_prices()
        )
        aug31 = series[series.index.normalize() == pd.Timestamp("2026-08-31", tz="UTC")]
        assert len(aug31) == 1
        assert float(aug31.iloc[0]) == pytest.approx(301.0)

    def test_index_dates_are_not_shifted_by_the_collapse(self) -> None:
        series: pd.Series = _reconstruct_live_equity(
            live_config=self._cfg(), prices=self._dual_bar_prices()
        )
        assert [ts.date().isoformat() for ts in series.index] == ["2026-08-31", "2026-09-01"]

    def test_a_day_that_cannot_be_fully_priced_is_omitted_not_zeroed(self) -> None:
        prices: pd.DataFrame = pd.DataFrame(
            {"SET:A": [10.0, float("nan")], "SET:B": [2.0, 3.0]},
            index=pd.DatetimeIndex(
                [
                    pd.Timestamp("2026-08-31 09:55", tz="Asia/Bangkok"),
                    pd.Timestamp("2026-09-01 09:55", tz="Asia/Bangkok"),
                ]
            ),
        )
        series: pd.Series = _reconstruct_live_equity(live_config=self._cfg(), prices=prices)
        assert [ts.date().isoformat() for ts in series.index] == ["2026-08-31"]
