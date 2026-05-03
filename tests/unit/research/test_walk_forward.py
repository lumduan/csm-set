"""Unit tests for WalkForwardAnalyzer and WalkForwardConfig."""

from pathlib import Path

import pandas as pd
import pytest

from csm.data.store import ParquetStore
from csm.research.backtest import BacktestConfig
from csm.research.exceptions import BacktestError
from csm.research.walk_forward import (
    WalkForwardAnalyzer,
    WalkForwardConfig,
    WalkForwardResult,
)

TZ: str = "Asia/Bangkok"


def _make_dates(n: int, start: str = "2010-01-31") -> list[pd.Timestamp]:
    return list(pd.date_range(start, periods=n, freq="ME", tz=TZ))


def _make_feature_panel(
    dates: list[pd.Timestamp],
    symbols: list[str],
    scores: list[list[float]],
) -> pd.DataFrame:
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
    return pd.DataFrame(price_matrix, index=pd.DatetimeIndex(dates), columns=symbols)


def _flat_returns_fixture(n_months: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (feature_panel, prices) for a simple n_months backtest with flat prices."""
    dates = _make_dates(n_months + 1)
    symbols = ["A", "B", "C", "D", "E"]
    scores = [[1.0, 0.8, 0.0, -0.5, -1.0]] * n_months
    feature_panel = _make_feature_panel(dates[:-1], symbols, scores)
    price_matrix = [[100.0] * 5] * (n_months + 1)
    prices = _make_prices(dates, symbols, price_matrix)
    return feature_panel, prices


@pytest.fixture
def store(tmp_path: Path) -> ParquetStore:
    return ParquetStore(tmp_path / "processed")


@pytest.fixture
def analyzer(store: ParquetStore) -> WalkForwardAnalyzer:
    return WalkForwardAnalyzer(store=store)


class TestWalkForwardSplitDates:
    """Unit tests for _split_dates fold construction."""

    def test_fold_count_matches_wf_config(self, analyzer: WalkForwardAnalyzer) -> None:
        """5-fold config with sufficient data produces exactly 5 (or fewer) folds."""
        dates = _make_dates(84)  # 7 years of monthly dates
        wf_config = WalkForwardConfig(n_folds=5, test_years=1, min_train_years=5)
        folds = analyzer._split_dates(dates, wf_config)
        # Must be ≤ 5 folds (may be fewer if data runs out)
        assert 1 <= len(folds) <= 5

    def test_expanding_windows_non_overlapping_test(self, analyzer: WalkForwardAnalyzer) -> None:
        """Adjacent fold test windows are contiguous (no gaps, no overlaps)."""
        dates = _make_dates(96)  # 8 years
        wf_config = WalkForwardConfig(n_folds=4, test_years=1, min_train_years=5)
        folds = analyzer._split_dates(dates, wf_config)
        for i in range(len(folds) - 1):
            _, _, test_end_i = folds[i]
            _, test_start_next, _ = folds[i + 1]
            # The test window end of fold i should equal the test start of fold i+1
            assert test_end_i == test_start_next

    def test_insufficient_data_raises_backtest_error(self, analyzer: WalkForwardAnalyzer) -> None:
        """Less than min_train + test years raises BacktestError."""
        dates = _make_dates(24)  # only 2 years
        wf_config = WalkForwardConfig(n_folds=3, test_years=1, min_train_years=5)
        with pytest.raises(BacktestError, match="at least"):
            analyzer._split_dates(dates, wf_config)

    def test_empty_dates_raises_backtest_error(self, analyzer: WalkForwardAnalyzer) -> None:
        """Empty date list raises BacktestError."""
        wf_config = WalkForwardConfig(n_folds=3, test_years=1, min_train_years=5)
        with pytest.raises(BacktestError):
            analyzer._split_dates([], wf_config)


class TestWalkForwardRun:
    """Integration-level tests for WalkForwardAnalyzer.run()."""

    def test_run_returns_walk_forward_result(self, analyzer: WalkForwardAnalyzer) -> None:
        """run() returns a WalkForwardResult with at least one fold."""
        feature_panel, prices = _flat_returns_fixture(84)  # 7 years
        config = BacktestConfig(
            transaction_cost_bps=0.0,
            n_holdings_min=2,
            n_holdings_max=3,
            buffer_rank_threshold=0.0,
            exit_rank_floor=0.0,
        )
        wf_config = WalkForwardConfig(n_folds=3, test_years=1, min_train_years=5)
        result = analyzer.run(feature_panel, prices, config, wf_config)
        assert isinstance(result, WalkForwardResult)
        assert len(result.folds) >= 1

    def test_aggregate_oos_metrics_keys_match_backtest(self, analyzer: WalkForwardAnalyzer) -> None:
        """aggregate_oos_metrics has the same keys as a normal BacktestResult.metrics."""
        feature_panel, prices = _flat_returns_fixture(84)
        config = BacktestConfig(
            transaction_cost_bps=0.0,
            n_holdings_min=2,
            n_holdings_max=3,
            buffer_rank_threshold=0.0,
            exit_rank_floor=0.0,
        )
        wf_config = WalkForwardConfig(n_folds=2, test_years=1, min_train_years=5)
        result = analyzer.run(feature_panel, prices, config, wf_config)
        expected_keys = {"cagr", "sharpe", "sortino", "calmar", "max_drawdown", "win_rate"}
        assert expected_keys.issubset(result.aggregate_oos_metrics.keys())

    def test_is_metrics_populated(self, analyzer: WalkForwardAnalyzer) -> None:
        """is_metrics dict is non-empty after a successful run."""
        feature_panel, prices = _flat_returns_fixture(84)
        config = BacktestConfig(
            transaction_cost_bps=0.0,
            n_holdings_min=2,
            n_holdings_max=3,
            buffer_rank_threshold=0.0,
            exit_rank_floor=0.0,
        )
        wf_config = WalkForwardConfig(n_folds=2, test_years=1, min_train_years=5)
        result = analyzer.run(feature_panel, prices, config, wf_config)
        assert result.is_metrics  # non-empty

    def test_insufficient_data_raises_backtest_error(self, analyzer: WalkForwardAnalyzer) -> None:
        """Fewer than min_train + test years of data raises BacktestError."""
        feature_panel, prices = _flat_returns_fixture(12)  # only 1 year
        config = BacktestConfig(
            transaction_cost_bps=0.0,
            n_holdings_min=1,
            n_holdings_max=2,
        )
        wf_config = WalkForwardConfig(n_folds=3, test_years=1, min_train_years=5)
        with pytest.raises(BacktestError):
            analyzer.run(feature_panel, prices, config, wf_config)

    def test_empty_feature_panel_raises_backtest_error(self, analyzer: WalkForwardAnalyzer) -> None:
        """Empty feature panel raises BacktestError immediately."""
        dates = _make_dates(84)
        symbols = ["A", "B"]
        empty_panel = pd.DataFrame(index=pd.MultiIndex.from_tuples([], names=["date", "symbol"]))
        prices = _make_prices(dates, symbols, [[100.0, 100.0]] * 84)
        config = BacktestConfig()
        wf_config = WalkForwardConfig(n_folds=2, test_years=1, min_train_years=5)
        with pytest.raises(BacktestError):
            analyzer.run(empty_panel, prices, config, wf_config)
