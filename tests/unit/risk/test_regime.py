"""Tests for regime detection."""

import numpy as np
import pandas as pd

from csm.risk.regime import RegimeDetector, RegimeState


def test_regime_transitions_on_known_price_series() -> None:
    detector: RegimeDetector = RegimeDetector()
    index: pd.DatetimeIndex = pd.date_range("2023-01-01", periods=260, freq="B", tz="Asia/Bangkok")
    bull_series: pd.Series = pd.Series(np.linspace(100.0, 150.0, 260), index=index)
    bear_series: pd.Series = pd.Series(np.linspace(150.0, 90.0, 260), index=index)
    flat_series: pd.Series = pd.Series(np.linspace(100.0, 101.0, 260), index=index)
    assert detector.detect(bull_series, index[-1]) is RegimeState.BULL
    assert detector.detect(bear_series, index[-1]) is RegimeState.BEAR
    assert detector.detect(flat_series, index[-1]) is RegimeState.NEUTRAL
