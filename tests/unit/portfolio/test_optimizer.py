"""Tests for portfolio optimizers."""

import pandas as pd
import pytest

from csm.portfolio.optimizer import WeightOptimizer


def test_equal_weight_sums_to_one() -> None:
    weights: pd.Series = WeightOptimizer().equal_weight(["A", "B", "C", "D"])
    assert float(weights.sum()) == pytest.approx(1.0)


def test_vol_target_output_shape(sample_prices: pd.DataFrame) -> None:
    returns: pd.DataFrame = sample_prices[["SET000", "SET001", "SET002"]].pct_change().dropna()
    weights: pd.Series = WeightOptimizer().vol_target_weight(
        ["SET000", "SET001", "SET002"], returns
    )
    assert list(weights.index) == ["SET000", "SET001", "SET002"]
