"""Tests for universe construction."""

import pandas as pd
import pytest

from csm.data.exceptions import UniverseError
from csm.data.universe import UniverseBuilder


def test_universe_filters_price_liquidity_and_coverage(sample_ohlcv_map: dict[str, pd.DataFrame]) -> None:
    bad_price: pd.DataFrame = sample_ohlcv_map["SET000"].copy()
    bad_price["close"] = 0.5
    bad_liquidity: pd.DataFrame = sample_ohlcv_map["SET001"].copy()
    bad_liquidity["volume"] = 100.0
    bad_coverage: pd.DataFrame = sample_ohlcv_map["SET002"].copy()
    bad_coverage.iloc[:200, bad_coverage.columns.get_loc("close")] = float("nan")
    sample_ohlcv_map["SET000"] = bad_price
    sample_ohlcv_map["SET001"] = bad_liquidity
    sample_ohlcv_map["SET002"] = bad_coverage

    universe: list[str] = UniverseBuilder().build(sample_ohlcv_map, as_of=pd.Timestamp("2024-12-31", tz="Asia/Bangkok"))
    assert "SET000" not in universe
    assert "SET001" not in universe
    assert "SET002" not in universe
    assert "SET003" in universe


def test_universe_raises_on_empty_result(sample_ohlcv_map: dict[str, pd.DataFrame]) -> None:
    for frame in sample_ohlcv_map.values():
        frame["close"] = 0.1
    with pytest.raises(UniverseError):
        UniverseBuilder().build(sample_ohlcv_map, as_of=pd.Timestamp("2024-12-31", tz="Asia/Bangkok"))