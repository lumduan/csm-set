"""Integration test for prices to feature to backtest flow."""

from pathlib import Path

import pandas as pd

from csm.data.store import ParquetStore
from csm.features.pipeline import FeaturePipeline
from csm.research.backtest import BacktestConfig, MomentumBacktest


def test_full_prices_to_backtest_pipeline(
    sample_ohlcv_map: dict[str, pd.DataFrame], sample_prices: pd.DataFrame, tmp_path: Path
) -> None:
    store: ParquetStore = ParquetStore(tmp_path / "processed")
    rebalance_dates: list[pd.Timestamp] = list(
        pd.date_range("2023-01-31", periods=6, freq="ME", tz="Asia/Bangkok")
    )
    feature_panel: pd.DataFrame = FeaturePipeline(store=store).build(
        sample_ohlcv_map, rebalance_dates
    )
    result = MomentumBacktest(store=store).run(
        feature_panel=feature_panel, prices=sample_prices, config=BacktestConfig()
    )
    assert result.metrics
    assert result.equity_curve
