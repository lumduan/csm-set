"""Tests for momentum feature calculations."""

import pandas as pd
import pytest

from csm.features.momentum import MomentumFeatures


def test_momentum_12_1_matches_manual_monthly_calculation(sample_prices: pd.DataFrame) -> None:
    monthly: pd.DataFrame = sample_prices.resample("ME").last()
    expected: pd.Series = (monthly.iloc[-2] / monthly.iloc[-14]) - 1.0
    result: pd.Series = MomentumFeatures().compute(sample_prices, formation_months=12, skip_months=1)
    pd.testing.assert_series_equal(result.sort_index(), expected.rename("mom_12_1").sort_index())