"""Unit tests for MomentumBacktest, BacktestConfig, and BacktestResult."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from csm.data.store import ParquetStore
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

    def test_raises_on_fewer_than_two_rebalance_dates(
        self, backtest: MomentumBacktest
    ) -> None:
        """BacktestError is raised when the panel has fewer than two distinct dates."""
        dates = _make_dates(1)
        feature_panel = _make_feature_panel(dates, ["A"], [[1.0]])
        prices = _make_prices(dates, ["A"], [[100.0]])
        with pytest.raises(BacktestError, match="At least two rebalance dates"):
            backtest.run(feature_panel=feature_panel, prices=prices, config=BacktestConfig())

    def test_raises_when_equity_curve_empty_after_loop(
        self, backtest: MomentumBacktest
    ) -> None:
        """BacktestError is raised when all periods are skipped due to missing prices."""
        dates = _make_dates(3)
        # Feature panel has symbols A and B; prices only has C.
        feature_panel = _make_feature_panel(
            dates[:2], ["A", "B"], [[1.0, -1.0], [1.0, -1.0]]
        )
        prices = _make_prices(dates, ["C"], [[100.0], [110.0], [120.0]])
        with pytest.raises(BacktestError, match="no output observations"):
            backtest.run(feature_panel=feature_panel, prices=prices, config=BacktestConfig())

    def test_metrics_dict_contains_no_raw_prices(self, backtest: MomentumBacktest) -> None:
        """metrics_dict() output contains no raw OHLCV field names."""
        dates = _make_dates(3)
        feature_panel = _make_feature_panel(
            dates[:2], ["A", "B"], [[1.0, -1.0], [1.0, -1.0]]
        )
        prices = _make_prices(
            dates, ["A", "B"], [[100.0, 100.0], [110.0, 105.0], [120.0, 115.0]]
        )
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
        cross_section = pd.DataFrame(
            {"signal": [1.0]}, index=pd.Index(["A"], name="symbol")
        )
        close = pd.DataFrame({"A": np.full(70, 1.0)}, index=dates)
        volume = pd.DataFrame({"A": np.full(70, 1.0)}, index=dates)  # ADTV=1 < 5M
        result = backtest._apply_adtv_filter(
            cross_section, close, volume, asof, min_adtv_thb=5_000_000.0
        )
        assert result.empty


class TestBufferLogic:
    def test_retains_holdings_when_replacement_ranks_below_threshold(
        self, backtest: MomentumBacktest
    ) -> None:
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
        result = backtest._apply_buffer_logic(current, candidates, cross_section, 0.125)
        assert "A" in result  # A retained (in candidates)
        assert "C" in result  # C admitted

    def test_retains_holding_below_buffer_threshold(self, backtest: MomentumBacktest) -> None:
        """Holding is kept when best replacement ranks < buffer_threshold better."""
        symbols = ["A", "B"]
        # Scores equal → ranks equal (both 0.75 with pct=True including ties handling)
        cross_section = pd.DataFrame(
            {"signal": [1.0, 0.95]}, index=pd.Index(symbols, name="symbol")
        )
        current = ["B"]
        candidates = ["A"]
        # rank diff = 1.0 - 0.5 = 0.5; with threshold=0.9, B is kept
        result = backtest._apply_buffer_logic(current, candidates, cross_section, 0.9)
        assert "B" in result


class TestSelectHoldings:
    def test_returns_at_least_n_min_when_universe_is_large(
        self, backtest: MomentumBacktest
    ) -> None:
        """With 100-symbol universe, result has exactly n_holdings_max symbols."""
        np.random.seed(42)
        symbols = [f"S{i:03d}" for i in range(100)]
        scores = np.random.randn(100).tolist()
        cross_section = pd.DataFrame(
            {"signal": scores}, index=pd.Index(symbols, name="symbol")
        )
        config = BacktestConfig(n_holdings_min=80, n_holdings_max=100)
        result = backtest._select_holdings(cross_section, config, [])
        assert len(result) == 100  # all 100 fit within max

    def test_returns_all_when_universe_smaller_than_n_min(
        self, backtest: MomentumBacktest
    ) -> None:
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
        idx_arr = np.concatenate(
            [np.linspace(100.0, 130.0, 230), np.linspace(130.0, 70.0, 20)]
        )
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
            soft_penalty_scoring=False,
        )
        config_safe = BacktestConfig(
            transaction_cost_bps=0.0,
            n_holdings_min=1,
            n_holdings_max=1,
            safe_mode_max_equity=0.2,
            soft_penalty_scoring=False,
        )
        result_bull = backtest.run(
            feature_panel=feature_panel, prices=prices, config=config_bull
        )
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

    def test_run_with_none_index_prices_stays_bull_mode(
        self, backtest: MomentumBacktest
    ) -> None:
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
            np.linspace(130.0, 40.0, 100),   # crash: sharp 70% drop
        ]
    )
    index_prices = pd.Series(prices_arr, index=all_dates)
    # Rebalance dates = last n_rebal+1 bars (deep in crash zone).
    rebal_dates = list(all_dates[-(n_rebal + 1):])
    return rebal_dates, index_prices


def _make_index_prices_weak_bear(dates: list[pd.Timestamp], tz: str = TZ) -> pd.Series:
    """Build an index price series below EMA-200 but with a flat/rising EMA slope.

    Only the very last bar drops below EMA, so the slope is still rising/flat.
    """
    warm_dates = pd.date_range("2018-01-01", periods=261, freq="B", tz=tz)
    warm_prices = np.linspace(100.0, 130.0, 261)
    warm_prices[-1] = 80.0  # single-bar dip below EMA; slope stays rising
    series = pd.Series(dict(zip(warm_dates, warm_prices)))
    for d in dates:
        series[d] = 80.0
    return series.sort_index()


class TestSoftPenaltyScoring:
    def test_penalty_reduces_score_of_underperformers(self, backtest: MomentumBacktest) -> None:
        """A stock with 12M return below SET index gets its score reduced (not removed)."""
        hist_dates = pd.date_range("2022-01-01", periods=260, freq="B", tz=TZ)
        index_prices = pd.Series(np.linspace(100.0, 120.0, 260), index=hist_dates)
        stock_a = pd.Series(np.linspace(100.0, 105.0, 260), index=hist_dates)  # underperform
        stock_b = pd.Series(np.linspace(100.0, 130.0, 260), index=hist_dates)  # outperform
        prices = pd.DataFrame({"A": stock_a, "B": stock_b})
        cross_section = pd.DataFrame(
            {"signal": [1.0, 0.8]}, index=pd.Index(["A", "B"], name="symbol")
        )
        asof = hist_dates[-1]
        result = backtest._apply_soft_penalty(
            cross_section, prices, index_prices, asof,
            lookback_months=12, penalty_rank_fraction=0.20,
        )
        # Both stocks remain in the cross_section (NOT removed).
        assert "A" in result.index
        assert "B" in result.index
        # A's score should be penalized (lowered) while B's stays at 0.8.
        # A was 1.0 → now 1.0 * 0.8 = 0.8; B stays at 0.8.
        assert float(result.loc["A", "signal"]) < 1.0
        assert float(result.loc["B", "signal"]) == 0.8

    def test_penalty_preserves_outperformers(self, backtest: MomentumBacktest) -> None:
        """A stock with return ≥ index return is NOT penalized."""
        hist_dates = pd.date_range("2022-01-01", periods=260, freq="B", tz=TZ)
        index_prices = pd.Series(np.linspace(100.0, 110.0, 260), index=hist_dates)
        stock = pd.Series(np.linspace(100.0, 110.0, 260), index=hist_dates)
        prices = pd.DataFrame({"A": stock})
        cross_section = pd.DataFrame(
            {"signal": [1.0]}, index=pd.Index(["A"], name="symbol")
        )
        asof = hist_dates[-1]
        result = backtest._apply_soft_penalty(
            cross_section, prices, index_prices, asof,
            lookback_months=12, penalty_rank_fraction=0.20,
        )
        # Outperformer — score unchanged.
        assert float(result.loc["A", "signal"]) == 1.0

    def test_penalty_skips_when_benchmark_history_insufficient(
        self, backtest: MomentumBacktest
    ) -> None:
        """Fewer than 2 index bars → penalty is skipped, cross_section unchanged."""
        asof = pd.Timestamp("2023-06-30", tz=TZ)
        index_prices = pd.Series(
            [100.0], index=pd.DatetimeIndex([asof], tz=TZ)
        )
        prices = pd.DataFrame(
            {"A": [100.0]}, index=pd.DatetimeIndex([asof], tz=TZ)
        )
        cross_section = pd.DataFrame(
            {"signal": [1.0]}, index=pd.Index(["A"], name="symbol")
        )
        result = backtest._apply_soft_penalty(
            cross_section, prices, index_prices, asof,
            lookback_months=12, penalty_rank_fraction=0.20,
        )
        assert len(result) == len(cross_section)
        assert float(result.loc["A", "signal"]) == 1.0

    def test_penalty_with_buffer_preserves_holdings(self, backtest: MomentumBacktest) -> None:
        """A penalized holding is retained if no replacement ranks buffer_threshold better."""
        hist_dates = pd.date_range("2022-01-01", periods=260, freq="B", tz=TZ)
        index_prices = pd.Series(np.linspace(100.0, 120.0, 260), index=hist_dates)
        # A underperforms but B does not.
        stock_a = pd.Series(np.linspace(100.0, 105.0, 260), index=hist_dates)
        stock_b = pd.Series(np.linspace(100.0, 130.0, 260), index=hist_dates)
        stock_c = pd.Series(np.linspace(100.0, 100.0, 260), index=hist_dates)  # flat
        prices = pd.DataFrame({"A": stock_a, "B": stock_b, "C": stock_c})
        asof = hist_dates[-1]
        cross_section = pd.DataFrame(
            {"signal": [1.0, 0.95, 0.01]},
            index=pd.Index(["A", "B", "C"], name="symbol"),
        )
        # Apply soft penalty — A gets penalized.
        penalized = backtest._apply_soft_penalty(
            cross_section, prices, index_prices, asof,
            lookback_months=12, penalty_rank_fraction=0.20,
        )
        # Now check buffer: A is current holding, ranked equally to candidate B.
        current = ["A"]
        # After penalty: A's score = 1.0 * 0.8 = 0.8, B = 0.95, C = 0.01
        # Composite scores (only signal column): A=0.8, B=0.95, C=0.01
        # Percentile ranks: C=0.33, A=0.67, B=1.0
        # Replacements for A from candidates: B (rank 1.0). Diff = 1.0 - 0.67 = 0.33
        # With buffer_threshold=0.9, A should be kept (0.33 < 0.9).
        candidates = ["B", "A"]
        buffered = backtest._apply_buffer_logic(current, candidates, penalized, 0.9)
        assert "A" in buffered


class TestDynamicBearMode:
    def test_strong_bear_uses_zero_equity(self, backtest: MomentumBacktest) -> None:
        """When EMA slope is negative (strong bear), equity weight = 0 → NAV stays flat."""
        rebal_dates, index_prices = _make_bear_index_and_dates(n_rebal=2)
        # Stock prices also crash so breadth stays low (no EARLY_BULL detection).
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
            soft_penalty_scoring=False,  # isolate the dynamic bear logic
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

    def test_bear_full_cash_false_uses_safe_mode_equity(
        self, backtest: MomentumBacktest
    ) -> None:
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
            soft_penalty_scoring=False,
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


class TestVolatilityExit:
    def test_excludes_stopped_out_holding(self, backtest: MomentumBacktest) -> None:
        """A holding that dropped 2×ATR below trailing peak is excluded."""
        dates = pd.date_range("2023-01-01", periods=300, freq="B", tz=TZ)
        asof = dates[-1]
        prices = pd.DataFrame(
            {
                "A": np.concatenate(
                    [np.linspace(100.0, 150.0, 250), np.linspace(150.0, 110.0, 50)]
                ),
                "B": np.linspace(100.0, 150.0, 300),  # always rising
            },
            index=dates,
        )
        current = ["A", "B"]
        # A drops from 150 to 110 (peak - 26.6% for atr_window=14). With ATR window 14
        # and simple close-to-close TR ≈ 0.8, 2×ATR ≈ 1.6. Stop = 150 - 1.6 = 148.4.
        # Since current price 110 < 148.4, A is stopped out.
        # B always rises — no stop trigger.
        result = backtest._apply_volatility_exit(
            current, prices, asof, atr_window=14, atr_multiplier=2.0, lookback_days=300,
        )
        assert "A" not in result
        assert "B" in result

    def test_keeps_normal_volatility_holding(self, backtest: MomentumBacktest) -> None:
        """A holding within 2×ATR of trailing peak is kept."""
        dates = pd.date_range("2023-01-01", periods=100, freq="B", tz=TZ)
        asof = dates[-1]
        # Monotonically rising — price at peak, stop never triggered.
        prices = pd.DataFrame(
            {"A": np.linspace(100.0, 101.0, 100)},
            index=dates,
        )
        result = backtest._apply_volatility_exit(
            ["A"], prices, asof, atr_window=14, atr_multiplier=2.0, lookback_days=100,
        )
        assert "A" in result

    def test_returns_empty_when_no_holdings(self, backtest: MomentumBacktest) -> None:
        """Empty holdings input → empty output."""
        dates = pd.date_range("2023-01-01", periods=100, freq="B", tz=TZ)
        prices = pd.DataFrame({"A": np.linspace(100.0, 150.0, 100)}, index=dates)
        result = backtest._apply_volatility_exit(
            [], prices, dates[-1], atr_window=14, atr_multiplier=2.0, lookback_days=100,
        )
        assert result == []


class TestEma50Warning:
    def test_warning_active_when_price_below_ema50(self, backtest: MomentumBacktest) -> None:
        """SET below EMA50 → True."""
        dates = pd.date_range("2020-01-01", periods=300, freq="B", tz="Asia/Bangkok")
        # Start high, recent crash below EMA50.
        prices_arr = np.concatenate(
            [np.linspace(100.0, 150.0, 270), np.linspace(150.0, 120.0, 30)]
        )
        prices = pd.Series(prices_arr, index=dates)
        asof = dates[-1]
        assert backtest._check_ema50_warning(prices, asof, window=50) is True

    def test_warning_inactive_when_price_above_ema50(self, backtest: MomentumBacktest) -> None:
        """SET above EMA50 → False."""
        dates = pd.date_range("2020-01-01", periods=300, freq="B", tz="Asia/Bangkok")
        prices = pd.Series(np.linspace(100.0, 150.0, 300), index=dates)
        asof = dates[-1]
        assert backtest._check_ema50_warning(prices, asof, window=50) is False

    def test_warning_inactive_when_insufficient_history(
        self, backtest: MomentumBacktest
    ) -> None:
        """Fewer than 50 bars → False (conservative default)."""
        dates = pd.date_range("2023-01-01", periods=30, freq="B", tz="Asia/Bangkok")
        prices = pd.Series(np.linspace(100.0, 80.0, 30), index=dates)
        assert backtest._check_ema50_warning(prices, dates[-1], window=50) is False
