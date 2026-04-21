"""Tests for the feature pipeline."""

from pathlib import Path

import pandas as pd

from csm.data.store import ParquetStore
from csm.features.pipeline import FeaturePipeline


def test_pipeline_z_scores_cross_sectionally(sample_ohlcv_map: dict[str, pd.DataFrame], tmp_path: Path) -> None:
    store: ParquetStore = ParquetStore(tmp_path / "processed")
    dates: list[pd.Timestamp] = [
        pd.Timestamp("2023-06-30", tz="Asia/Bangkok"),
        pd.Timestamp("2023-12-29", tz="Asia/Bangkok"),
    ]
    panel: pd.DataFrame = FeaturePipeline(store=store).build(sample_ohlcv_map, dates)
    for date in panel.index.get_level_values("date").unique():
        snapshot: pd.DataFrame = panel.xs(date, level="date")
        assert abs(float(snapshot.mean().mean())) < 1e-6
