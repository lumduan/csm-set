"""Unit tests for MomentumBacktest, BacktestConfig, and BacktestResult."""

from pathlib import Path

import pandas as pd
import pytest

from csm.data.store import ParquetStore
from csm.research.backtest import BacktestConfig, MomentumBacktest
from csm.research.exceptions import BacktestError

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
        # A and B rank in the top 40%; C, D, E are below.
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
        config = BacktestConfig(top_quantile=0.4, transaction_cost_bps=0.0)

        result = backtest.run(feature_panel=feature_panel, prices=prices, config=config)

        # top_quantile=0.4, 5 symbols → n_select = round(5*0.4) = 2 → A, B selected.
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

        # top_quantile=0.5, 2 symbols → n_select = round(2*0.5)=1 → only A selected.
        config_zero = BacktestConfig(top_quantile=0.5, transaction_cost_bps=0.0)
        config_cost = BacktestConfig(top_quantile=0.5, transaction_cost_bps=15.0)

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
            config=BacktestConfig(top_quantile=0.5, transaction_cost_bps=0.0),
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
            config=BacktestConfig(top_quantile=0.5, transaction_cost_bps=0.0),
        )
        curve_dict = result.equity_curve_dict()
        # Description must declare the NAV base.
        assert "NAV indexed to 100" in curve_dict["description"]
        # With A returning 10% and zero cost, first NAV = 100 * 1.10 = 110.
        first_nav = curve_dict["series"][0]["nav"]
        assert pytest.approx(first_nav, rel=1e-4) == 110.0
