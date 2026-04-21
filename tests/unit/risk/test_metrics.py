"""Tests for performance metrics."""

import numpy as np
import pandas as pd
import pytest

from csm.risk.metrics import PerformanceMetrics


def test_sharpe_matches_manual_calculation() -> None:
    equity_curve: pd.Series = pd.Series(
        [100.0, 102.0, 104.0, 103.0, 107.0],
        index=pd.date_range("2024-01-31", periods=5, freq="ME", tz="Asia/Bangkok"),
    )
    metrics: dict[str, float] = PerformanceMetrics().summary(equity_curve)
    returns: pd.Series = equity_curve.pct_change().dropna()
    expected_sharpe: float = float((returns.mean() * 12.0 - 0.02) / (returns.std(ddof=0) * np.sqrt(12.0)))
    assert metrics["sharpe"] == pytest.approx(expected_sharpe)
