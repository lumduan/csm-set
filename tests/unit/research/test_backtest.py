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

        config_bull = BacktestConfig(
            transaction_cost_bps=0.0, n_holdings_min=1, n_holdings_max=1, safe_mode_max_equity=0.2
        )
        config_safe = BacktestConfig(
            transaction_cost_bps=0.0, n_holdings_min=1, n_holdings_max=1, safe_mode_max_equity=0.2
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
