"""Integration test for prices to feature to backtest flow."""

import logging
from pathlib import Path

import pandas as pd
import pytest

from csm.data.store import ParquetStore
from csm.features.pipeline import FeaturePipeline
from csm.research.backtest import BacktestConfig, MomentumBacktest


def test_full_prices_to_backtest_pipeline(
    sample_ohlcv_map: dict[str, pd.DataFrame],
    sample_prices: pd.DataFrame,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store: ParquetStore = ParquetStore(tmp_path / "processed")
    rebalance_dates: list[pd.Timestamp] = list(
        pd.date_range("2023-01-31", periods=6, freq="ME", tz="Asia/Bangkok")
    )
    pipeline: FeaturePipeline = FeaturePipeline(store=store)
    feature_panel: pd.DataFrame = pipeline.build(sample_ohlcv_map, rebalance_dates)
    # Phase 3.8: thread volumes through so the ADTV filter actually fires.
    volumes: pd.DataFrame = pipeline.build_volume_matrix()
    assert not volumes.empty, "build_volume_matrix() should return non-empty matrix from fixture"

    with caplog.at_level(logging.WARNING, logger="csm.research.backtest"):
        result = MomentumBacktest(store=store).run(
            feature_panel=feature_panel,
            prices=sample_prices,
            config=BacktestConfig(),
            volumes=volumes,
        )
    assert result.metrics
    assert result.equity_curve
    # Confirm the ADTV-skipped warning is NOT emitted — volumes were threaded successfully.
    assert not any(
        "volumes not provided" in rec.message for rec in caplog.records
    ), "ADTV filter unexpectedly skipped — volume threading broken"
