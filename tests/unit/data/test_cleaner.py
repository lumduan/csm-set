"""Tests for the price cleaner."""

import numpy as np
import pandas as pd
import pytest

from csm.data.cleaner import PriceCleaner


def test_cleaner_fills_short_gaps_and_drops_high_missing_columns() -> None:
    index: pd.DatetimeIndex = pd.date_range("2024-01-01", periods=20, freq="B", tz="Asia/Bangkok")
    frame: pd.DataFrame = pd.DataFrame(
        {
            "A": np.linspace(10.0, 20.0, 20),
            "B": np.linspace(5.0, 6.0, 20),
            "C": np.linspace(100.0, 110.0, 20),
        },
        index=index,
    )
    frame.loc[index[5:8], "A"] = np.nan
    frame.loc[index[:10], "B"] = np.nan
    cleaned: pd.DataFrame = PriceCleaner().clean(frame)
    assert "B" not in cleaned.columns
    assert cleaned["A"].isna().sum() == 0


def test_compute_returns_matches_log_formula() -> None:
    prices: pd.DataFrame = pd.DataFrame({"A": [100.0, 110.0, 121.0]})
    returns: pd.DataFrame = PriceCleaner().compute_returns(prices)
    assert returns.iloc[0, 0] == pytest.approx(np.log(1.1))