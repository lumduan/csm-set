"""Tests for IC analysis."""

import pandas as pd

from csm.research.ic_analysis import ICAnalyzer


def test_ic_matches_known_synthetic_signal() -> None:
    index: pd.DatetimeIndex = pd.date_range("2024-01-31", periods=3, freq="ME", tz="Asia/Bangkok")
    signals: pd.DataFrame = pd.DataFrame(
        [[1.0, 2.0, 3.0], [1.0, 3.0, 5.0], [2.0, 4.0, 6.0]], index=index, columns=["A", "B", "C"]
    )
    returns: pd.DataFrame = signals * 2.0
    analyzer: ICAnalyzer = ICAnalyzer()
    ic: pd.DataFrame = analyzer.compute_ic(signals, returns)
    assert (ic["ic"] > 0.99).all()
