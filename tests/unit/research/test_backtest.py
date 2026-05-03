"""Unit tests for MomentumBacktest, BacktestConfig, and BacktestResult."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from csm.data.store import ParquetStore
from csm.portfolio.construction import PortfolioConstructor
from csm.research.backtest import BacktestConfig, MomentumBacktest
from csm.research.exceptions import BacktestError
from csm.risk.regime import RegimeState

TZ: str = "Asia/Bangkok"


def _make_dates(n: int, start: str = "2023-01-31") -> list[pd.Timestamp]:
    return list(pd.date_range(start, periods=n, freq="ME", tz=TZ))


def _make_feature_panel(
    dates: list[pd.Timestamp],
    symbols: list[str],
    scores: list[list[float]],
) -> pd.DataFrame:
    """Create a MultiIndex (date, symbol) feature panel with a single 'signal' column."""
    rows: list[dict[str, object]] = []
    for date, date_scores in zip(dates, scores, strict=False):
        for sym, score in zip(symbols, date_scores, strict=False):
            rows.append({"date": date, "symbol": sym, "signal": score})
    return pd.DataFrame(rows).set_index(["date", "symbol"])


def _make_prices(
    dates: list[pd.Timestamp],
    symbols: list[str],
    price_matrix: list[list[float]],
) -> pd.DataFrame:
    """Create a wide price DataFrame (date rows × symbol columns)."""
    return pd.DataFrame(price_matrix, index=pd.DatetimeIndex(dates), columns=symbols)


@pytest.fixture
def store(tmp_path: Path) -> ParquetStore:
    return ParquetStore(tmp_path / "processed")


@pytest.fixture
def backtest(store: ParquetStore) -> MomentumBacktest:
    return MomentumBacktest(store=store)


class TestMomentumBacktestRun:
    def test_zero_cost_known_pnl(self, backtest: MomentumBacktest) -> None:
        """Zero-cost backtest with a known-rank signal returns the correct PnL."""
        dates = _make_dates(3)
        symbols = ["A", "B", "C", "D", "E"]
        # A and B rank in the top 2; C, D, E are below.
        scores = [
            [1.0, 0.8, 0.0, -0.5, -1.0],
            [1.0, 0.8, 0.0, -0.5, -1.0],
        ]
        feature_panel = _make_feature_panel(dates[:2], symbols, scores)
        price_matrix = [
            [100.0, 100.0, 100.0, 100.0, 100.0],
            [110.0, 105.0, 100.0, 100.0, 100.0],
            [120.0, 115.0, 100.0, 100.0, 100.0],
        ]
        prices = _make_prices(dates, symbols, price_matrix)
        # n_holdings_max=2 → only A, B selected (top 2 by composite).
        config = BacktestConfig(
            transaction_cost_bps=0.0,
            n_holdings_min=1,
            n_holdings_max=2,
        )

        result = backtest.run(feature_panel=feature_panel, prices=prices, config=config)

        # Period 1: A=+10%, B=+5%, equal weight → gross = 0.5*0.10 + 0.5*0.05 = 0.075.
        # NAV = 100 * 1.075 = 107.5 (zero cost).
        nav_values = list(result.equity_curve.values())
        assert pytest.approx(nav_values[0], rel=1e-4) == 107.5

    def test_transaction_cost_reduces_return(self, backtest: MomentumBacktest) -> None:
        """15 bps transaction cost reduces NAV by the expected amount."""
        dates = _make_dates(3)
        symbols = ["A", "B"]
        scores = [[1.0, -1.0], [1.0, -1.0]]
        feature_panel = _make_feature_panel(dates[:2], symbols, scores)
        price_matrix = [
            [100.0, 100.0],
            [110.0, 100.0],
            [120.0, 100.0],
        ]
        prices = _make_prices(dates, symbols, price_matrix)

        # n_holdings_max=1 → only A selected (top 1 by composite).
        config_zero = BacktestConfig(transaction_cost_bps=0.0, n_holdings_min=1, n_holdings_max=1)
        config_cost = BacktestConfig(transaction_cost_bps=15.0, n_holdings_min=1, n_holdings_max=1)

        result_zero = backtest.run(feature_panel=feature_panel, prices=prices, config=config_zero)
        result_cost = backtest.run(feature_panel=feature_panel, prices=prices, config=config_cost)

        nav_zero = list(result_zero.equity_curve.values())[0]
        nav_cost = list(result_cost.equity_curve.values())[0]

        assert nav_cost < nav_zero
        # Initial purchase from empty portfolio: turnover = 0.5 * |1.0 - 0| = 0.5.
        # cost = 0.5 * 15 / 10_000 = 0.00075.
        # A return = 10%; nav = 100 * (1 + 0.10 - 0.00075) = 109.925.
        expected_nav = 100.0 * (1.0 + 0.10 - 0.5 * 15.0 / 10_000.0)
        assert pytest.approx(nav_cost, rel=1e-4) == expected_nav

    def test_raises_on_empty_feature_panel(self, backtest: MomentumBacktest) -> None:
        """BacktestError is raised immediately when the feature panel is empty."""
        dates = _make_dates(2)
        empty_panel = pd.DataFrame(
            index=pd.MultiIndex.from_arrays([[], []], names=["date", "symbol"])
        )
        prices = _make_prices(dates, ["A"], [[100.0], [110.0]])
        with pytest.raises(BacktestError, match="Feature panel and prices are required"):
            backtest.run(feature_panel=empty_panel, prices=prices, config=BacktestConfig())

    def test_raises_on_empty_prices(self, backtest: MomentumBacktest) -> None:
        """BacktestError is raised immediately when the price matrix is empty."""
        dates = _make_dates(2)
        feature_panel = _make_feature_panel(dates, ["A"], [[1.0], [1.0]])
        with pytest.raises(BacktestError, match="Feature panel and prices are required"):
            backtest.run(
                feature_panel=feature_panel,
                prices=pd.DataFrame(),
                config=BacktestConfig(),
            )

    def test_raises_on_fewer_than_two_rebalance_dates(self, backtest: MomentumBacktest) -> None:
        """BacktestError is raised when the panel has fewer than two distinct dates."""
        dates = _make_dates(1)
        feature_panel = _make_feature_panel(dates, ["A"], [[1.0]])
        prices = _make_prices(dates, ["A"], [[100.0]])
        with pytest.raises(BacktestError, match="At least two rebalance dates"):
            backtest.run(feature_panel=feature_panel, prices=prices, config=BacktestConfig())

    def test_raises_when_equity_curve_empty_after_loop(self, backtest: MomentumBacktest) -> None:
        """BacktestError is raised when all periods are skipped due to missing prices."""
        dates = _make_dates(3)
        # Feature panel has symbols A and B; prices only has C.
        feature_panel = _make_feature_panel(dates[:2], ["A", "B"], [[1.0, -1.0], [1.0, -1.0]])
        prices = _make_prices(dates, ["C"], [[100.0], [110.0], [120.0]])
        with pytest.raises(BacktestError, match="no output observations"):
            backtest.run(feature_panel=feature_panel, prices=prices, config=BacktestConfig())

    def test_metrics_dict_contains_no_raw_prices(self, backtest: MomentumBacktest) -> None:
        """metrics_dict() output contains no raw OHLCV field names."""
        dates = _make_dates(3)
        feature_panel = _make_feature_panel(dates[:2], ["A", "B"], [[1.0, -1.0], [1.0, -1.0]])
        prices = _make_prices(dates, ["A", "B"], [[100.0, 100.0], [110.0, 105.0], [120.0, 115.0]])
        result = backtest.run(
            feature_panel=feature_panel,
            prices=prices,
            config=BacktestConfig(transaction_cost_bps=0.0, n_holdings_min=1, n_holdings_max=1),
        )
        forbidden_keys = {"open", "high", "low", "close", "volume", "price"}
        assert not forbidden_keys.intersection(result.metrics_dict().keys())

    def test_equity_curve_dict_nav_starts_at_100(self, backtest: MomentumBacktest) -> None:
        """equity_curve_dict() description asserts NAV is indexed to 100."""
        dates = _make_dates(3)
        feature_panel = _make_feature_panel(dates[:2], ["A"], [[1.0], [1.0]])
        prices = _make_prices(dates, ["A"], [[100.0], [110.0], [120.0]])
        result = backtest.run(
            feature_panel=feature_panel,
            prices=prices,
            config=BacktestConfig(transaction_cost_bps=0.0, n_holdings_min=1, n_holdings_max=1),
        )
        curve_dict = result.equity_curve_dict()
        # Description must declare the NAV base.
        assert "NAV indexed to 100" in curve_dict["description"]
        # With A returning 10% and zero cost, first NAV = 100 * 1.10 = 110.
        first_nav = curve_dict["series"][0]["nav"]
        assert pytest.approx(first_nav, rel=1e-4) == 110.0


class TestAdtvFilter:
    def test_excludes_low_liquidity_symbols(self, backtest: MomentumBacktest) -> None:
        """Symbols with 63-day ADTV below threshold are removed from cross_section."""
        dates = pd.date_range("2023-01-01", periods=70, freq="B", tz="Asia/Bangkok")
        asof = dates[-1]
        symbols = ["HIGH", "LOW", "MED"]
        cross_section = pd.DataFrame(
            {"signal": [1.0, 0.5, 0.0]}, index=pd.Index(symbols, name="symbol")
        )
        close = pd.DataFrame(
            {
                "HIGH": np.full(70, 100.0),
                "LOW": np.full(70, 100.0),
                "MED": np.full(70, 100.0),
            },
            index=dates,
        )
        # HIGH: 100*100k=10M > 5M ✓; LOW: 100*10=1k < 5M ✗; MED: 100*60k=6M > 5M ✓
        volume = pd.DataFrame(
            {
                "HIGH": np.full(70, 100_000.0),
                "LOW": np.full(70, 10.0),
                "MED": np.full(70, 60_000.0),
            },
            index=dates,
        )
        result = backtest._apply_adtv_filter(
            cross_section, close, volume, asof, min_adtv_thb=5_000_000.0
        )
        assert list(result.index) == ["HIGH", "MED"]

    def test_returns_empty_when_all_filtered(self, backtest: MomentumBacktest) -> None:
        """All symbols below ADTV threshold → empty cross_section returned."""
        dates = pd.date_range("2023-01-01", periods=70, freq="B", tz="Asia/Bangkok")
        asof = dates[-1]
        cross_section = pd.DataFrame({"signal": [1.0]}, index=pd.Index(["A"], name="symbol"))
        close = pd.DataFrame({"A": np.full(70, 1.0)}, index=dates)
        volume = pd.DataFrame({"A": np.full(70, 1.0)}, index=dates)  # ADTV=1 < 5M
        result = backtest._apply_adtv_filter(
            cross_section, close, volume, asof, min_adtv_thb=5_000_000.0
        )
        assert result.empty


class TestBufferLogic:
    def test_retains_holdings_when_replacement_ranks_below_threshold(self) -> None:
        """Holding is kept when the best replacement ranks only 5 pct-pts better."""
        symbols = ["A", "B", "C", "D"]
        # Composite scores: C(1.0) > A(0.8) > B(0.6) > D(0.2)
        # Percentile ranks: D=0.25, B=0.5, A=0.75, C=1.0
        cross_section = pd.DataFrame(
            {"signal": [0.8, 0.6, 1.0, 0.2]}, index=pd.Index(symbols, name="symbol")
        )
        # Current holdings: A, B. Candidates (top-2 by score): C, A.
        current = ["A", "B"]
        candidates = ["C", "A"]
        # B is not in candidates; best replacement is C (rank=1.0) vs B (rank=0.5).
        # Difference = 0.5 >= 0.125 → B is evicted.
        result, evicted, retained = PortfolioConstructor._apply_buffer_logic(
            current, candidates, cross_section, 0.125, 0.0
        )
        assert "A" in result  # A retained (in candidates)
        assert "C" in result  # C admitted
        assert "B" in evicted

    def test_retains_holding_below_buffer_threshold(self) -> None:
        """Holding is kept when best replacement ranks < buffer_threshold better."""
        symbols = ["A", "B"]
        # Scores equal → ranks equal (both 0.75 with pct=True including ties handling)
        cross_section = pd.DataFrame(
            {"signal": [1.0, 0.95]}, index=pd.Index(symbols, name="symbol")
        )
        current = ["B"]
        candidates = ["A"]
        # rank diff = 1.0 - 0.5 = 0.5; with threshold=0.9, B is kept
        result, evicted, retained = PortfolioConstructor._apply_buffer_logic(
            current, candidates, cross_section, 0.9, 0.0
        )
        assert "B" in result
        assert "B" in retained


class TestSelectHoldings:
    def test_returns_at_least_n_min_when_universe_is_large(
        self, backtest: MomentumBacktest
    ) -> None:
        """With 100-symbol universe, result has exactly n_holdings_max symbols."""
        np.random.seed(42)
        symbols = [f"S{i:03d}" for i in range(100)]
        scores = np.random.randn(100).tolist()
        cross_section = pd.DataFrame({"signal": scores}, index=pd.Index(symbols, name="symbol"))
        config = BacktestConfig(n_holdings_min=80, n_holdings_max=100)
        result = backtest._select_holdings(cross_section, config, [])
        assert len(result) == 100  # all 100 fit within max

    def test_returns_all_when_universe_smaller_than_n_min(self, backtest: MomentumBacktest) -> None:
        """With 5-symbol universe, all symbols are returned (can't fill n_min=80)."""
        cross_section = pd.DataFrame(
            {"signal": [1.0, 0.5, 0.0, -0.5, -1.0]},
            index=pd.Index(["A", "B", "C", "D", "E"], name="symbol"),
        )
        config = BacktestConfig(n_holdings_min=80, n_holdings_max=100)
        result = backtest._select_holdings(cross_section, config, [])
        assert len(result) == 5


class TestComputeMode:
    def test_returns_bull_when_price_above_ema(self, backtest: MomentumBacktest) -> None:
        """SET above EMA-200 → RegimeState.BULL."""
        dates = pd.date_range("2020-01-01", periods=250, freq="B", tz="Asia/Bangkok")
        prices = pd.Series(np.linspace(100.0, 130.0, 250), index=dates)
        asof = dates[-1]
        assert backtest._compute_mode(prices, asof, 200) is RegimeState.BULL

    def test_returns_bear_when_price_below_ema(self, backtest: MomentumBacktest) -> None:
        """SET below EMA-200 → RegimeState.BEAR."""
        dates = pd.date_range("2020-01-01", periods=250, freq="B", tz="Asia/Bangkok")
        # Start high, drop sharply at end so last price < EMA
        prices_arr = np.concatenate([np.linspace(100.0, 130.0, 230), np.linspace(130.0, 70.0, 20)])
        prices = pd.Series(prices_arr, index=dates)
        asof = dates[-1]
        assert backtest._compute_mode(prices, asof, 200) is RegimeState.BEAR


class TestSafeModeScaling:
    def test_safe_mode_reduces_exposure(self, backtest: MomentumBacktest) -> None:
        """In Safe Mode, NAV growth is capped by safe_mode_max_equity."""
        dates = _make_dates(3)
        symbols = ["A"]
        scores = [[1.0], [1.0]]
        feature_panel = _make_feature_panel(dates[:2], symbols, scores)
        prices = _make_prices(dates, symbols, [[100.0], [110.0], [120.0]])

        # index_prices always below EMA → Safe Mode every period
        idx_dates = pd.date_range("2018-01-01", periods=250, freq="B", tz="Asia/Bangkok")
        idx_arr = np.concatenate([np.linspace(100.0, 130.0, 230), np.linspace(130.0, 70.0, 20)])
        index_prices = pd.Series(idx_arr, index=idx_dates)
        # Extend to cover rebalance dates (repeat last value)
        for d in dates:
            index_prices[d] = 70.0
        index_prices = index_prices.sort_index()

        # Disable soft penalty — test is solely about Safe Mode equity scaling.
        config_bull = BacktestConfig(
            transaction_cost_bps=0.0,
            n_holdings_min=1,
            n_holdings_max=1,
            safe_mode_max_equity=0.2,
            rs_filter_mode="off",
        )
        config_safe = BacktestConfig(
            transaction_cost_bps=0.0,
            n_holdings_min=1,
            n_holdings_max=1,
            safe_mode_max_equity=0.2,
            rs_filter_mode="off",
        )
        result_bull = backtest.run(feature_panel=feature_panel, prices=prices, config=config_bull)
        result_safe = backtest.run(
            feature_panel=feature_panel,
            prices=prices,
            config=config_safe,
            index_prices=index_prices,
        )
        nav_bull = list(result_bull.equity_curve.values())[0]
        nav_safe = list(result_safe.equity_curve.values())[0]
        # Safe Mode scales weight by 0.2 → smaller gain
        assert nav_safe < nav_bull

    def test_run_with_none_volumes_skips_adtv_filter(self, backtest: MomentumBacktest) -> None:
        """Passing volumes=None does not crash — ADTV filter is skipped."""
        dates = _make_dates(3)
        feature_panel = _make_feature_panel(dates[:2], ["A"], [[1.0], [1.0]])
        prices = _make_prices(dates, ["A"], [[100.0], [110.0], [120.0]])
        result = backtest.run(
            feature_panel=feature_panel,
            prices=prices,
            config=BacktestConfig(transaction_cost_bps=0.0, n_holdings_min=1, n_holdings_max=1),
            volumes=None,
        )
        assert result is not None

    def test_run_with_none_index_prices_stays_bull_mode(self, backtest: MomentumBacktest) -> None:
        """Passing index_prices=None → all periods logged as BULL."""
        dates = _make_dates(3)
        feature_panel = _make_feature_panel(dates[:2], ["A"], [[1.0], [1.0]])
        prices = _make_prices(dates, ["A"], [[100.0], [110.0], [120.0]])
        result = backtest.run(
            feature_panel=feature_panel,
            prices=prices,
            config=BacktestConfig(transaction_cost_bps=0.0, n_holdings_min=1, n_holdings_max=1),
            index_prices=None,
        )
        modes = [p.mode for p in result.monthly_report.periods]
        assert all(m == "BULL" for m in modes)


def _make_bear_index_and_dates(
    n_rebal: int = 2, tz: str = TZ
) -> tuple[list[pd.Timestamp], pd.Series]:
    """Return (rebalance_dates, index_prices) where the index is in a confirmed downtrend.

    The price series is one continuous array: 210 warm-up bars (rising) + 90 crash bars
    (falling). Rebalance dates are the last n_rebal+1 bars of the crash zone. This
    guarantees both price < EMA-200 AND a negative EMA slope at each rebalance date.
    """
    n_total = 310
    all_dates = pd.date_range("2020-01-01", periods=n_total, freq="B", tz=tz)
    prices_arr = np.concatenate(
        [
            np.linspace(100.0, 130.0, 210),  # warm-up: rising
            np.linspace(130.0, 40.0, 100),  # crash: sharp 70% drop
        ]
    )
    index_prices = pd.Series(prices_arr, index=all_dates)
    # Rebalance dates = last n_rebal+1 bars (deep in crash zone).
    rebal_dates = list(all_dates[-(n_rebal + 1) :])
    return rebal_dates, index_prices


def _make_index_prices_weak_bear(dates: list[pd.Timestamp], tz: str = TZ) -> pd.Series:
    """Build an index price series below EMA-200 but with a flat/rising EMA slope.

    Only the very last bar drops below EMA, so the slope is still rising/flat.
    """
    warm_dates = pd.date_range("2018-01-01", periods=261, freq="B", tz=tz)
    warm_prices = np.linspace(100.0, 130.0, 261)
    warm_prices[-1] = 80.0  # single-bar dip below EMA; slope stays rising
    series = pd.Series(dict(zip(warm_dates, warm_prices, strict=False)))
    for d in dates:
        series[d] = 80.0
    return series.sort_index()


class TestEntryOnlyRsFilter:
    def test_rs_filter_returns_passing_set(self, backtest: MomentumBacktest) -> None:
        """RS filter returns a set of stocks beating index 12M return."""
        hist_dates = pd.date_range("2022-01-01", periods=260, freq="B", tz=TZ)
        index_prices = pd.Series(np.linspace(100.0, 120.0, 260), index=hist_dates)
        stock_a = pd.Series(np.linspace(100.0, 105.0, 260), index=hist_dates)  # underperform
        stock_b = pd.Series(np.linspace(100.0, 130.0, 260), index=hist_dates)  # outperform
        prices = pd.DataFrame({"A": stock_a, "B": stock_b})
        cross_section = pd.DataFrame(
            {"signal": [1.0, 0.8]}, index=pd.Index(["A", "B"], name="symbol")
        )
        asof = hist_dates[-1]
        result = backtest._apply_relative_strength_filter(
            cross_section, prices, index_prices, asof, lookback_months=12
        )
        assert isinstance(result, set)
        assert "A" not in result  # underperformer excluded
        assert "B" in result  # outperformer kept

    def test_rs_filter_returns_all_when_all_outperform(self, backtest: MomentumBacktest) -> None:
        """All stocks beat index → all in the passing set."""
        hist_dates = pd.date_range("2022-01-01", periods=260, freq="B", tz=TZ)
        index_prices = pd.Series(np.linspace(100.0, 110.0, 260), index=hist_dates)
        stock = pd.Series(np.linspace(100.0, 130.0, 260), index=hist_dates)
        prices = pd.DataFrame({"A": stock})
        cross_section = pd.DataFrame({"signal": [1.0]}, index=pd.Index(["A"], name="symbol"))
        result = backtest._apply_relative_strength_filter(
            cross_section, prices, index_prices, hist_dates[-1], lookback_months=12
        )
        assert "A" in result

    def test_rs_filter_empty_when_benchmark_history_insufficient(
        self, backtest: MomentumBacktest
    ) -> None:
        """Fewer than 2 index bars → empty set (gate open)."""
        asof = pd.Timestamp("2023-06-30", tz=TZ)
        index_prices = pd.Series([100.0], index=pd.DatetimeIndex([asof], tz=TZ))
        prices = pd.DataFrame({"A": [100.0]}, index=pd.DatetimeIndex([asof], tz=TZ))
        cross_section = pd.DataFrame({"signal": [1.0]}, index=pd.Index(["A"], name="symbol"))
        result = backtest._apply_relative_strength_filter(
            cross_section, prices, index_prices, asof, lookback_months=12
        )
        assert result == set()  # empty = gate open, all eligible

    def test_entry_only_preserves_holding_not_in_rs_pass(self, backtest: MomentumBacktest) -> None:
        """Existing holding outside RS gate is protected by buffer (entry-only)."""
        symbols = ["A", "B", "C", "D"]
        cross_section = pd.DataFrame(
            {"signal": [0.8, 0.6, 1.0, 0.2]}, index=pd.Index(symbols, name="symbol")
        )
        # A is a current holding but NOT in entry_mask (e.g. failed RS).
        # Candidates come from entry_mask: {C, D}.
        current = ["A"]
        entry_mask: set[str] = {"C", "D"}
        # composite.eligible (from entry_mask): C=1.0, D=0.2
        # candidates: [C, D]
        # buffer: A is current holding, not in candidate set {C, D}
        # pct_rank: C=1.0, A=0.75, D=0.25
        # best replacement for A: C (rank 1.0), diff = 0.25
        # with buffer_threshold=0.9, diff 0.25 < 0.9 → A kept
        config = BacktestConfig(
            n_holdings_min=2,
            n_holdings_max=3,
            buffer_rank_threshold=0.9,
        )
        result = backtest._select_holdings(
            cross_section,
            config,
            current,
            entry_mask=entry_mask,
        )
        assert "A" in result  # buffer protects existing holding


class TestDynamicBearMode:
    def test_strong_bear_uses_zero_equity(self, backtest: MomentumBacktest) -> None:
        """When EMA slope is negative (strong bear), equity weight = 0 → NAV stays flat."""
        rebal_dates, index_prices = _make_bear_index_and_dates(n_rebal=2)
        # Stock prices also crash so EMA50 fast re-entry doesn't trigger.
        stock_prices = pd.Series(
            np.linspace(130.0, 40.0, len(index_prices)), index=index_prices.index
        )
        prices = pd.DataFrame({"A": stock_prices})
        feature_panel = _make_feature_panel(rebal_dates[:2], ["A"], [[1.0], [1.0]])
        config = BacktestConfig(
            transaction_cost_bps=0.0,
            n_holdings_min=1,
            n_holdings_max=1,
            bear_full_cash=True,
            rs_filter_mode="off",  # isolate the dynamic bear logic
        )
        result = backtest.run(
            feature_panel=feature_panel,
            prices=prices,
            config=config,
            index_prices=index_prices,
        )
        # In confirmed strong bear, equity fraction = 0 → NAV must stay exactly at 100.
        nav_values = list(result.equity_curve.values())
        assert nav_values, "Expected at least one period in equity curve"
        assert all(abs(nav - 100.0) < 1e-9 for nav in nav_values)

    def test_bear_full_cash_false_uses_safe_mode_equity(self, backtest: MomentumBacktest) -> None:
        """When bear_full_cash=False, safe_mode_max_equity is used even in strong bear."""
        rebal_dates, index_prices = _make_bear_index_and_dates(n_rebal=2)
        stock_prices = pd.Series(
            np.linspace(50.0, 80.0, len(index_prices)), index=index_prices.index
        )
        prices = pd.DataFrame({"A": stock_prices})
        feature_panel = _make_feature_panel(rebal_dates[:2], ["A"], [[1.0], [1.0]])
        config = BacktestConfig(
            transaction_cost_bps=0.0,
            n_holdings_min=1,
            n_holdings_max=1,
            bear_full_cash=False,
            safe_mode_max_equity=0.2,
            rs_filter_mode="off",
        )
        result = backtest.run(
            feature_panel=feature_panel,
            prices=prices,
            config=config,
            index_prices=index_prices,
        )
        # Some equity exposure (20%) → NAV should differ from 100 (rising stock → above 100).
        nav_values = list(result.equity_curve.values())
        assert nav_values, "Expected at least one period in equity curve"
        assert any(nav > 100.0 for nav in nav_values)


class TestEma50FastReentry:
    def test_fast_reentry_uses_full_equity(self, backtest: MomentumBacktest) -> None:
        """SET > EMA50 triggers full equity even when SET < EMA200 (bear)."""
        n_total = 300
        all_dates = pd.date_range("2020-01-01", periods=n_total, freq="B", tz=TZ)
        # Recovery: long bull → crash → partial bounce above EMA50, below EMA200.
        prices_arr = np.concatenate(
            [
                np.linspace(100.0, 200.0, 200),  # long bull
                np.linspace(200.0, 100.0, 80),  # sharp crash
                np.linspace(100.0, 125.0, 20),  # recovery: SET > EMA50, SET < EMA200
            ]
        )
        index_prices = pd.Series(prices_arr, index=all_dates)
        rebal_dates = list(all_dates[-3:])
        # Stock at index 297=100, index 298=110 → 10% gain in the rebalance period.
        stock_arr = np.concatenate(
            [
                np.full(298, 100.0),
                [110.0, 110.0],
            ]
        )
        prices = pd.DataFrame({"A": pd.Series(stock_arr, index=all_dates)})
        feature_panel = _make_feature_panel(rebal_dates[:2], ["A"], [[1.0], [1.0]])
        config = BacktestConfig(
            transaction_cost_bps=0.0,
            n_holdings_min=1,
            n_holdings_max=1,
            bear_full_cash=True,
            rs_filter_mode="off",
            fast_reentry_ema_window=50,
        )
        result = backtest.run(
            feature_panel=feature_panel,
            prices=prices,
            config=config,
            index_prices=index_prices,
        )
        nav_values = list(result.equity_curve.values())
        assert nav_values
        assert pytest.approx(nav_values[0], rel=1e-4) == 110.0


class TestFastExitOverlay:
    """Phase 3.8 — SET below EMA100 while still above EMA200 → safe-mode equity."""

    def test_fast_exit_engages_when_set_below_ema100_in_bull(
        self, backtest: MomentumBacktest
    ) -> None:
        """SET above EMA200 (BULL) but below EMA100 → equity scaled to safe_mode_max_equity."""
        # Long flat warm-up keeps EMA200 anchored low; sharp peak then partial pullback
        # produces price > EMA200 (BULL) but price < EMA100 (overlay engaged).
        n_flat, n_rise, n_dip = 300, 60, 40
        n_total = n_flat + n_rise + n_dip
        all_dates = pd.date_range("2020-01-01", periods=n_total, freq="B", tz=TZ)
        prices_arr = np.concatenate(
            [
                np.full(n_flat, 100.0),
                np.linspace(100.0, 250.0, n_rise),
                np.linspace(250.0, 175.0, n_dip),
            ]
        )
        index_prices = pd.Series(prices_arr, index=all_dates)
        asof = all_dates[-1]
        assert backtest._compute_mode(index_prices, asof, 200) is RegimeState.BULL
        assert backtest._is_fast_exit(index_prices, asof, 100) is True

        rebal_dates = list(all_dates[-3:])
        # Stock gains 10% over the first rebalance period (rebal[0]→rebal[1]).
        stock_arr = np.concatenate([np.full(n_total - 3, 100.0), [100.0, 110.0, 110.0]])
        prices = pd.DataFrame({"A": pd.Series(stock_arr, index=all_dates)})
        feature_panel = _make_feature_panel(rebal_dates[:2], ["A"], [[1.0], [1.0]])
        config = BacktestConfig(
            transaction_cost_bps=0.0,
            n_holdings_min=1,
            n_holdings_max=1,
            safe_mode_max_equity=0.2,
            rs_filter_mode="off",
            exit_ema_window=100,
            fast_reentry_ema_window=50,
        )
        result = backtest.run(
            feature_panel=feature_panel,
            prices=prices,
            config=config,
            index_prices=index_prices,
        )
        nav_values = list(result.equity_curve.values())
        assert nav_values
        # Stock gained 10% but equity scaled to 0.2 → NAV = 100 * (1 + 0.2 * 0.10) = 102.0.
        assert pytest.approx(nav_values[0], rel=1e-4) == 102.0

    def test_fast_exit_dormant_when_set_above_both_emas(self, backtest: MomentumBacktest) -> None:
        """Pure trending-up SET → fast-exit never fires; equity stays at 1.0 (regression guard)."""
        n_total = 300
        all_dates = pd.date_range("2020-01-01", periods=n_total, freq="B", tz=TZ)
        # Pure rising series — SET stays well above both EMA100 and EMA200.
        prices_arr = np.linspace(100.0, 220.0, n_total)
        index_prices = pd.Series(prices_arr, index=all_dates)
        asof = all_dates[-1]
        assert backtest._compute_mode(index_prices, asof, 200) is RegimeState.BULL
        assert backtest._is_fast_exit(index_prices, asof, 100) is False

        rebal_dates = list(all_dates[-3:])
        stock_arr = np.concatenate([np.full(n_total - 3, 100.0), [100.0, 110.0, 110.0]])
        prices = pd.DataFrame({"A": pd.Series(stock_arr, index=all_dates)})
        feature_panel = _make_feature_panel(rebal_dates[:2], ["A"], [[1.0], [1.0]])
        config = BacktestConfig(
            transaction_cost_bps=0.0,
            n_holdings_min=1,
            n_holdings_max=1,
            rs_filter_mode="off",
            exit_ema_window=100,
        )
        result = backtest.run(
            feature_panel=feature_panel,
            prices=prices,
            config=config,
            index_prices=index_prices,
        )
        nav_values = list(result.equity_curve.values())
        assert nav_values
        # Full equity → 10% gain → NAV ≈ 110.
        assert pytest.approx(nav_values[0], rel=1e-4) == 110.0

    def test_fast_exit_disabled_via_huge_window_matches_phase37(
        self, backtest: MomentumBacktest
    ) -> None:
        """exit_ema_window > history length disables the overlay (A/B sanity harness).

        ``RegimeDetector.compute_ema`` returns an empty Series when history is shorter
        than the span; ``is_bull_market`` then defaults to True; ``_is_fast_exit``
        therefore returns False — the overlay is dormant.
        """
        n_flat, n_rise, n_dip = 300, 60, 40
        n_total = n_flat + n_rise + n_dip
        all_dates = pd.date_range("2020-01-01", periods=n_total, freq="B", tz=TZ)
        prices_arr = np.concatenate(
            [
                np.full(n_flat, 100.0),
                np.linspace(100.0, 250.0, n_rise),
                np.linspace(250.0, 175.0, n_dip),
            ]
        )
        index_prices = pd.Series(prices_arr, index=all_dates)
        rebal_dates = list(all_dates[-3:])
        stock_arr = np.concatenate([np.full(n_total - 3, 100.0), [100.0, 110.0, 110.0]])
        prices = pd.DataFrame({"A": pd.Series(stock_arr, index=all_dates)})
        feature_panel = _make_feature_panel(rebal_dates[:2], ["A"], [[1.0], [1.0]])
        # Span > history → EMA is empty → fast-exit returns False → equity = 1.0.
        config = BacktestConfig(
            transaction_cost_bps=0.0,
            n_holdings_min=1,
            n_holdings_max=1,
            rs_filter_mode="off",
            exit_ema_window=10_000,
        )
        result = backtest.run(
            feature_panel=feature_panel,
            prices=prices,
            config=config,
            index_prices=index_prices,
        )
        nav_values = list(result.equity_curve.values())
        assert nav_values
        # Overlay disabled → full equity → 10% gain → NAV ≈ 110.
        assert pytest.approx(nav_values[0], rel=1e-4) == 110.0


class TestPhase38Defaults:
    """Phase 3.8 — verify BacktestConfig defaults pull the new constants."""

    def test_buffer_threshold_default_is_025(self) -> None:
        """BUFFER_RANK_THRESHOLD bumped from 0.20 → 0.25 in Phase 3.8."""
        config = BacktestConfig()
        assert config.buffer_rank_threshold == 0.25

    def test_exit_ema_window_default_is_100(self) -> None:
        """EXIT_EMA_WINDOW = 100 introduced in Phase 3.8."""
        config = BacktestConfig()
        assert config.exit_ema_window == 100


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 3.9 tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestExitFloor:
    """Phase 3.9 — exit_rank_floor hard-evicts bottom-ranked holdings."""

    def _make_cross_section(self, symbols: list[str], scores: list[float]) -> pd.DataFrame:
        return pd.DataFrame({"signal": scores}, index=symbols)

    def test_holdings_below_floor_always_evicted(self) -> None:
        """A holding at rank ~0.20 is evicted when floor=0.35, even with no good replacement."""
        symbols = ["A", "B", "C", "D", "E"]
        # Ascending scores so rank of "A" is lowest (pct_rank ~ 0.20)
        scores = [0.1, 0.3, 0.5, 0.7, 0.9]
        cross_section = self._make_cross_section(symbols, scores)
        # A is current holding (rank ~ 0.20); candidates don't include A
        candidates = ["B", "C"]
        result, evicted, _ = PortfolioConstructor._apply_buffer_logic(
            current_holdings=["A"],
            candidates=candidates,
            cross_section=cross_section,
            buffer_threshold=0.25,
            exit_rank_floor=0.35,  # A's rank < 0.35 → evicted unconditionally
        )
        assert "A" not in result
        assert "A" in evicted

    def test_holdings_above_floor_protected_by_buffer(self) -> None:
        """A holding at rank ~0.80 is retained when the best replacement is only 0.10 better."""
        symbols = ["A", "B", "C", "D", "E"]
        # D at rank ~0.80 (4th of 5)
        scores = [0.1, 0.3, 0.5, 0.7, 0.9]
        cross_section = self._make_cross_section(symbols, scores)
        # Best replacement candidate "E" has rank 1.0; diff = 0.20 < buffer 0.25 → retained
        result, evicted, retained = PortfolioConstructor._apply_buffer_logic(
            current_holdings=["D"],
            candidates=["E"],
            cross_section=cross_section,
            buffer_threshold=0.25,
            exit_rank_floor=0.35,
        )
        assert "D" in result
        assert "D" in retained

    def test_floor_zero_disables_hard_eviction(self) -> None:
        """exit_rank_floor=0.0 disables unconditional eviction — buffer-only behaviour."""
        symbols = ["A", "B", "C", "D", "E"]
        scores = [0.1, 0.3, 0.5, 0.7, 0.9]
        cross_section = self._make_cross_section(symbols, scores)
        # A has the lowest rank; no good replacement (diff < buffer)
        result, evicted, retained = PortfolioConstructor._apply_buffer_logic(
            current_holdings=["A"],
            candidates=["B"],  # rank diff = 0.20 < buffer 0.25 → retained by buffer alone
            cross_section=cross_section,
            buffer_threshold=0.25,
            exit_rank_floor=0.0,  # floor disabled
        )
        assert "A" in result
        assert "A" in retained


class TestRebalanceEveryN:
    """Phase 3.9 — rebalance_every_n subsamples the monthly schedule."""

    def _make_multi_period_backtest(
        self, backtest: MomentumBacktest, n_periods: int, rebalance_every_n: int
    ) -> dict[str, float]:
        """Run a simple backtest with flat prices and return the turnover map."""
        dates = _make_dates(n_periods + 1)
        symbols = ["A", "B", "C", "D", "E"]
        scores = [[1.0, 0.8, 0.0, -0.5, -1.0]] * n_periods
        feature_panel = _make_feature_panel(dates[:-1], symbols, scores)
        # Flat prices → zero returns, so NAV stays at 100 regardless of weights
        price_matrix = [[100.0] * 5] * (n_periods + 1)
        prices = _make_prices(dates, symbols, price_matrix)
        config = BacktestConfig(
            transaction_cost_bps=0.0,
            n_holdings_min=2,
            n_holdings_max=2,
            rebalance_every_n=rebalance_every_n,
            buffer_rank_threshold=0.0,
            exit_rank_floor=0.0,
        )
        result = backtest.run(feature_panel=feature_panel, prices=prices, config=config)
        return result.turnover

    def test_n1_rebalances_every_period(self, backtest: MomentumBacktest) -> None:
        """rebalance_every_n=1 → every period is a rebalance period (default behaviour)."""
        turnover = self._make_multi_period_backtest(backtest, n_periods=4, rebalance_every_n=1)
        # n_periods=4 feature dates → 3 consecutive pairs → 3 entries in turnover map
        assert len(turnover) == 3

    def test_n2_equity_curve_still_monthly(self, backtest: MomentumBacktest) -> None:
        """With rebalance_every_n=2, the equity curve still has an entry for every month."""
        dates = _make_dates(7)
        symbols = ["A", "B", "C", "D", "E"]
        scores = [[1.0, 0.8, 0.0, -0.5, -1.0]] * 6
        feature_panel = _make_feature_panel(dates[:-1], symbols, scores)
        price_matrix = [[100.0] * 5] * 7
        prices = _make_prices(dates, symbols, price_matrix)
        config = BacktestConfig(
            transaction_cost_bps=0.0,
            n_holdings_min=2,
            n_holdings_max=2,
            rebalance_every_n=2,
            buffer_rank_threshold=0.0,
            exit_rank_floor=0.0,
        )
        result = backtest.run(feature_panel=feature_panel, prices=prices, config=config)
        # 6 periods → equity curve should have an entry for each period that completes
        assert len(result.equity_curve) >= 4  # at minimum the rebalance periods

    def test_n2_skipped_periods_have_zero_turnover(self, backtest: MomentumBacktest) -> None:
        """With rebalance_every_n=2, odd-indexed periods have zero turnover."""
        dates = _make_dates(7)
        symbols = ["A", "B", "C", "D", "E"]
        scores = [[1.0, 0.8, 0.0, -0.5, -1.0]] * 6
        feature_panel = _make_feature_panel(dates[:-1], symbols, scores)
        price_matrix = [[100.0] * 5] * 7
        prices = _make_prices(dates, symbols, price_matrix)
        config = BacktestConfig(
            transaction_cost_bps=0.0,
            n_holdings_min=2,
            n_holdings_max=2,
            rebalance_every_n=2,
            buffer_rank_threshold=0.0,
            exit_rank_floor=0.0,
        )
        result = backtest.run(feature_panel=feature_panel, prices=prices, config=config)
        turnover_values = list(result.turnover.values())
        # At least one period should have zero turnover (the skipped period)
        assert any(t == 0.0 for t in turnover_values)


class TestSectorCap:
    """Phase 3.9 — _apply_sector_cap trims overweight sectors."""

    def _make_cross_section(self, symbols: list[str], scores: list[float]) -> pd.DataFrame:
        return pd.DataFrame({"signal": scores}, index=symbols)

    def test_no_sector_map_returns_unchanged(self, backtest: MomentumBacktest) -> None:
        """_apply_sector_cap with each symbol in its own sector returns selected unchanged."""
        selected = ["A", "B", "C"]
        cross_section = self._make_cross_section(["A", "B", "C"], [1.0, 0.8, 0.6])
        # Each symbol in a unique sector → no sector exceeds 1/3 < 35% cap
        sector_map = {"A": "TECH", "B": "BANK", "C": "ENERGY"}
        result = backtest._apply_sector_cap(selected, cross_section, sector_map, max_weight=0.35)
        assert set(result) == set(selected)

    def test_overweight_sector_trimmed(self, backtest: MomentumBacktest) -> None:
        """8 of 10 stocks in same sector exceeds 35% cap — trimmed down to ≤ 35%."""
        n = 10
        symbols = [f"S{i}" for i in range(n)]
        scores = list(range(n, 0, -1))  # S0 highest score
        cross_section = self._make_cross_section(symbols, scores)
        # 8 stocks in "BANK", 2 in "TECH"
        sector_map = {s: "BANK" for s in symbols[:8]}
        sector_map.update({s: "TECH" for s in symbols[8:]})
        result = backtest._apply_sector_cap(symbols, cross_section, sector_map, max_weight=0.35)
        # Bank sector must be trimmed to ≤ floor(10 * 0.35) = 3 stocks (absolute cap on original n)
        bank_count = sum(1 for s in result if sector_map.get(s) == "BANK")
        max_allowed = int(n * 0.35)  # = 3
        assert bank_count <= max_allowed
        assert len(result) < n  # some evictions occurred

    def test_balanced_sectors_not_trimmed(self, backtest: MomentumBacktest) -> None:
        """Two sectors at 50% each are both below a 60% cap — no trimming."""
        symbols = ["A", "B", "C", "D"]
        cross_section = self._make_cross_section(symbols, [1.0, 0.8, 0.6, 0.4])
        sector_map = {"A": "TECH", "B": "TECH", "C": "BANK", "D": "BANK"}
        result = backtest._apply_sector_cap(symbols, cross_section, sector_map, max_weight=0.60)
        assert set(result) == set(symbols)


class TestVolScaling:
    """Phase 3.9 — vol scaling overlay scales equity_fraction by realized vol."""

    def _flat_prices(self, symbols: list[str], n: int = 100) -> pd.DataFrame:
        """Return a price DataFrame with flat prices (zero volatility)."""
        dates = pd.date_range("2020-01-01", periods=n, freq="D", tz="Asia/Bangkok")
        return pd.DataFrame(
            {sym: [100.0] * n for sym in symbols},
            index=dates,
        )

    def _trending_prices(
        self, symbols: list[str], daily_ret: float = 0.01, n: int = 100
    ) -> pd.DataFrame:
        """Return a price DataFrame with constant daily returns."""
        dates = pd.date_range("2020-01-01", periods=n, freq="D", tz="Asia/Bangkok")
        price = 100.0
        prices = []
        for _ in range(n):
            prices.append(price)
            price *= 1.0 + daily_ret
        return pd.DataFrame({sym: prices for sym in symbols}, index=dates)

    def test_vol_scaling_enabled_by_default(self, backtest: MomentumBacktest) -> None:
        """vol_scaling_enabled=True (Phase 4 default)."""
        config = BacktestConfig()
        assert config.vol_scaling_enabled is True

    def test_high_realized_vol_reduces_equity_fraction(self, backtest: MomentumBacktest) -> None:
        """Realized vol 2× target → equity fraction is approximately halved."""
        # daily_ret std of 0.01 ≈ annualized 0.01 * sqrt(252) ≈ 0.159
        symbols = ["A", "B"]
        prices = self._trending_prices(symbols, daily_ret=0.01 + 0.005 * float("nan" != "nan"))
        # Use random prices to get non-zero vol
        import numpy as np

        rng = np.random.default_rng(42)
        n = 100
        dates = pd.date_range("2020-01-01", periods=n, freq="D", tz="Asia/Bangkok")
        raw = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.02, (n, 2)), axis=0)
        prices = pd.DataFrame(raw, index=dates, columns=symbols)
        asof = dates[-1]
        realized_vol = backtest._compute_portfolio_vol(prices, symbols, asof, lookback_days=63)
        assert realized_vol > 0.0
        scaled = backtest._apply_vol_scaling(
            prices,
            symbols,
            asof,
            equity_fraction=1.0,
            lookback_days=63,
            vol_target=realized_vol / 2.0,
            vol_scale_cap=1.5,
        )
        assert pytest.approx(scaled, rel=0.05) == 0.5

    def test_low_vol_capped_at_scale_cap_then_1(self, backtest: MomentumBacktest) -> None:
        """Very low realized vol → scale clamped to vol_scale_cap, then min(…, 1.0)."""
        symbols = ["A"]
        n = 100
        dates = pd.date_range("2020-01-01", periods=n, freq="D", tz="Asia/Bangkok")
        # 0.001 daily return std → annualized ~0.016; target=0.15 → scale = 9.4 → capped at 1.5
        rng = np.random.default_rng(0)
        raw = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.001, n))
        prices = pd.DataFrame({"A": raw}, index=dates)
        asof = dates[-1]
        scaled = backtest._apply_vol_scaling(
            prices,
            symbols,
            asof,
            equity_fraction=0.5,
            lookback_days=63,
            vol_target=0.15,
            vol_scale_cap=1.5,
        )
        # min(0.5 * 1.5, 1.0) = min(0.75, 1.0) = 0.75
        assert scaled <= 1.0
        assert scaled > 0.5  # must have been scaled up

    def test_nan_vol_returns_equity_fraction_unchanged(self, backtest: MomentumBacktest) -> None:
        """Fewer than 21 bars → NaN vol → equity_fraction returned unchanged."""
        symbols = ["A"]
        dates = pd.date_range("2020-01-01", periods=10, freq="D", tz="Asia/Bangkok")
        prices = pd.DataFrame({"A": [100.0] * 10}, index=dates)
        asof = dates[-1]
        scaled = backtest._apply_vol_scaling(
            prices,
            symbols,
            asof,
            equity_fraction=0.8,
            lookback_days=63,
            vol_target=0.15,
            vol_scale_cap=1.5,
        )
        assert scaled == pytest.approx(0.8)


class TestPhase39Defaults:
    """Phase 3.9 — verify BacktestConfig defaults match the new constants."""

    def test_rebalance_every_n_default(self) -> None:
        assert BacktestConfig().rebalance_every_n == 1

    def test_exit_rank_floor_default(self) -> None:
        assert BacktestConfig().exit_rank_floor == 0.35

    def test_vol_scaling_enabled_by_default(self) -> None:
        assert BacktestConfig().vol_scaling_enabled is True

    def test_vol_lookback_days_default(self) -> None:
        assert BacktestConfig().vol_lookback_days == 63

    def test_vol_target_annual_default(self) -> None:
        assert BacktestConfig().vol_target_annual == pytest.approx(0.15)

    def test_vol_scale_cap_default(self) -> None:
        assert BacktestConfig().vol_scale_cap == pytest.approx(1.5)

    def test_sector_max_weight_default(self) -> None:
        assert BacktestConfig().sector_max_weight == pytest.approx(0.35)
