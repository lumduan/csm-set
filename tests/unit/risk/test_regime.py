"""Tests for regime detection."""

import numpy as np
import pandas as pd
import pytest

from csm.risk.regime import RegimeDetector, RegimeState


def test_regime_transitions_on_known_price_series() -> None:
    detector: RegimeDetector = RegimeDetector()
    index: pd.DatetimeIndex = pd.date_range("2023-01-01", periods=260, freq="B", tz="Asia/Bangkok")
    bull_series: pd.Series = pd.Series(np.linspace(100.0, 150.0, 260), index=index)
    bear_series: pd.Series = pd.Series(np.linspace(150.0, 90.0, 260), index=index)
    flat_series: pd.Series = pd.Series(np.full(260, 100.0), index=index)
    assert detector.detect(bull_series, index[-1]) is RegimeState.BULL
    assert detector.detect(bear_series, index[-1]) is RegimeState.BEAR
    assert detector.detect(flat_series, index[-1]) is RegimeState.NEUTRAL


class TestComputeEma:
    def test_returns_empty_for_series_shorter_than_window(self) -> None:
        prices = pd.Series(np.linspace(100.0, 110.0, 50))
        result = RegimeDetector.compute_ema(prices, window=200)
        assert result.empty

    def test_returns_series_same_length_as_input_for_sufficient_history(self) -> None:
        prices = pd.Series(np.linspace(100.0, 130.0, 250))
        result = RegimeDetector.compute_ema(prices, window=200)
        assert len(result) == len(prices)

    def test_ema_lags_behind_sharp_rise(self) -> None:
        """EMA should be below the last price after a sharp run-up."""
        prices = pd.Series(np.concatenate([np.full(200, 100.0), np.full(50, 200.0)]))
        ema = RegimeDetector.compute_ema(prices, window=200)
        assert float(ema.iloc[-1]) < float(prices.iloc[-1])

    def test_ema_above_last_price_after_sharp_drop(self) -> None:
        """EMA should be above the last price after a sharp crash."""
        prices = pd.Series(np.concatenate([np.full(200, 100.0), np.linspace(100.0, 50.0, 50)]))
        ema = RegimeDetector.compute_ema(prices, window=200)
        assert float(ema.iloc[-1]) > float(prices.iloc[-1])


class TestIsBullMarket:
    def test_returns_true_when_price_above_ema(self) -> None:
        detector = RegimeDetector()
        dates = pd.date_range("2020-01-01", periods=250, freq="B", tz="Asia/Bangkok")
        prices = pd.Series(np.linspace(100.0, 130.0, 250), index=dates)
        assert detector.is_bull_market(prices, dates[-1], window=200) is True

    def test_returns_false_when_price_below_ema(self) -> None:
        detector = RegimeDetector()
        dates = pd.date_range("2020-01-01", periods=250, freq="B", tz="Asia/Bangkok")
        prices_arr = np.concatenate([np.linspace(100.0, 130.0, 230), np.linspace(130.0, 70.0, 20)])
        prices = pd.Series(prices_arr, index=dates)
        assert detector.is_bull_market(prices, dates[-1], window=200) is False

    def test_defaults_to_true_when_insufficient_history(self) -> None:
        """Fewer than 200 bars → default to Bull (conservative warm-up assumption)."""
        detector = RegimeDetector()
        dates = pd.date_range("2023-01-01", periods=100, freq="B", tz="Asia/Bangkok")
        prices = pd.Series(np.linspace(100.0, 80.0, 100), index=dates)
        assert detector.is_bull_market(prices, dates[-1], window=200) is True

    def test_asof_slices_correctly(self) -> None:
        """Only data up to asof should be used — future data must not affect result."""
        detector = RegimeDetector()
        dates = pd.date_range("2020-01-01", periods=300, freq="B", tz="Asia/Bangkok")
        # First 250 bars: rising (Bull). Last 50 bars: crash (would flip to Bear).
        prices_arr = np.concatenate([np.linspace(100.0, 130.0, 250), np.linspace(130.0, 50.0, 50)])
        prices = pd.Series(prices_arr, index=dates)
        # Cut off at bar 250 — should still be Bull.
        assert detector.is_bull_market(prices, dates[249], window=200) is True


class TestHasNegativeEmaSlope:
    def test_returns_true_when_ema_is_falling(self) -> None:
        """Sustained decline → EMA is falling → True."""
        detector = RegimeDetector()
        # 250 rising bars to warm up, then 50 sharply falling to make EMA slope negative.
        dates = pd.date_range("2020-01-01", periods=300, freq="B", tz="Asia/Bangkok")
        prices_arr = np.concatenate([np.linspace(100.0, 130.0, 250), np.linspace(130.0, 60.0, 50)])
        prices = pd.Series(prices_arr, index=dates)
        # At the last date the EMA should be declining.
        assert (
            detector.has_negative_ema_slope(prices, dates[-1], window=200, slope_lookback=21)
            is True
        )

    def test_returns_false_when_ema_is_rising(self) -> None:
        """Sustained rise → EMA is rising → False."""
        detector = RegimeDetector()
        dates = pd.date_range("2020-01-01", periods=260, freq="B", tz="Asia/Bangkok")
        prices = pd.Series(np.linspace(100.0, 150.0, 260), index=dates)
        assert (
            detector.has_negative_ema_slope(prices, dates[-1], window=200, slope_lookback=21)
            is False
        )

    def test_returns_false_when_insufficient_history(self) -> None:
        """Fewer than window + slope_lookback bars → False (conservative default)."""
        detector = RegimeDetector()
        dates = pd.date_range("2023-01-01", periods=210, freq="B", tz="Asia/Bangkok")
        prices = pd.Series(np.linspace(100.0, 80.0, 210), index=dates)
        # Only 210 bars but we need ≥ 200+22 = 222 → insufficient for slope check.
        assert (
            detector.has_negative_ema_slope(prices, dates[-1], window=200, slope_lookback=21)
            is False
        )
