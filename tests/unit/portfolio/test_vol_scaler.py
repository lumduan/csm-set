"""Tests for VolatilityScaler."""

import math

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from csm.portfolio.vol_scaler import (
    VolatilityScaler,
    VolScalingConfig,
    VolScalingResult,
)

TZ: str = "Asia/Bangkok"


@pytest.fixture
def uniform_weights() -> pd.Series:
    """5-symbol equal-weight Series summing to 1.0."""
    return pd.Series(0.2, index=["A", "B", "C", "D", "E"], dtype=float)


@pytest.fixture
def concentrated_weights() -> pd.Series:
    """Skewed weight distribution summing to 1.0."""
    return pd.Series(
        [0.5, 0.25, 0.125, 0.0625, 0.0625],
        index=["A", "B", "C", "D", "E"],
        dtype=float,
    )


@pytest.fixture
def volatile_prices() -> pd.DataFrame:
    """200 days of synthetic prices for 5 symbols, ~20% annualized vol each."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2023-01-01", periods=200, freq="B", tz=TZ)
    symbols = ["A", "B", "C", "D", "E"]
    data: dict[str, np.ndarray] = {}
    for sym in symbols:
        daily_ret = rng.normal(0.0005, 0.012, len(dates))
        data[sym] = 100.0 * np.exp(np.cumsum(daily_ret))
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def low_vol_prices() -> pd.DataFrame:
    """200 days of synthetic prices, ~2% annualized vol."""
    rng = np.random.default_rng(99)
    dates = pd.date_range("2023-01-01", periods=200, freq="B", tz=TZ)
    symbols = ["A", "B", "C", "D", "E"]
    data: dict[str, np.ndarray] = {}
    for sym in symbols:
        daily_ret = rng.normal(0.0005, 0.0012, len(dates))
        data[sym] = 100.0 * np.exp(np.cumsum(daily_ret))
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def constant_prices() -> pd.DataFrame:
    """200 days of flat prices (zero realized vol)."""
    dates = pd.date_range("2023-01-01", periods=200, freq="B", tz=TZ)
    data: dict[str, list[float]] = {}
    for sym in ["A", "B", "C", "D", "E"]:
        data[sym] = [100.0] * len(dates)
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def insufficient_prices() -> pd.DataFrame:
    """Only 15 days of data — below the 21-bar minimum."""
    rng = np.random.default_rng(7)
    dates = pd.date_range("2023-01-01", periods=15, freq="B", tz=TZ)
    symbols = ["A", "B", "C", "D", "E"]
    data: dict[str, np.ndarray] = {}
    for sym in symbols:
        daily_ret = rng.normal(0.0005, 0.012, len(dates))
        data[sym] = 100.0 * np.exp(np.cumsum(daily_ret))
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def single_asset_prices() -> pd.DataFrame:
    """200 days of synthetic prices for a single symbol."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2023-01-01", periods=200, freq="B", tz=TZ)
    daily_ret = rng.normal(0.0005, 0.012, len(dates))
    data = {"A": 100.0 * np.exp(np.cumsum(daily_ret))}
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def scaler() -> VolatilityScaler:
    return VolatilityScaler()


class TestVolScalingConfig:
    def test_defaults(self) -> None:
        config = VolScalingConfig()
        assert config.enabled is True
        assert config.target_annual == pytest.approx(0.15)
        assert config.lookback_days == 63
        assert config.cap == pytest.approx(1.5)
        assert config.floor == pytest.approx(0.0)
        assert config.regime_aware is False

    def test_custom_values(self) -> None:
        config = VolScalingConfig(
            enabled=False,
            target_annual=0.12,
            lookback_days=126,
            cap=2.0,
            floor=0.1,
            regime_aware=True,
        )
        assert config.enabled is False
        assert config.target_annual == pytest.approx(0.12)
        assert config.lookback_days == 126
        assert config.cap == pytest.approx(2.0)
        assert config.floor == pytest.approx(0.1)
        assert config.regime_aware is True

    def test_target_annual_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            VolScalingConfig(target_annual=0.0)

    def test_lookback_minimum(self) -> None:
        with pytest.raises(ValidationError):
            VolScalingConfig(lookback_days=10)

    def test_cap_minimum(self) -> None:
        with pytest.raises(ValidationError):
            VolScalingConfig(cap=0.5)


class TestVolScalingResult:
    def test_default_construction(self) -> None:
        result = VolScalingResult(
            realized_vol_annual=0.20,
            scale_factor=0.75,
            equity_fraction=0.75,
        )
        assert result.realized_vol_annual == pytest.approx(0.20)
        assert result.scale_factor == pytest.approx(0.75)
        assert result.equity_fraction == pytest.approx(0.75)


class TestVolatilityScaler:
    def test_disabled_pass_through(
        self, scaler: VolatilityScaler, uniform_weights: pd.Series, volatile_prices: pd.DataFrame,
    ) -> None:
        """enabled=False returns weights unchanged with scale_factor=1.0."""
        config = VolScalingConfig(enabled=False)
        scaled, result = scaler.scale(uniform_weights, volatile_prices, config)
        pd.testing.assert_series_equal(scaled, uniform_weights)
        assert result.scale_factor == pytest.approx(1.0)
        assert result.equity_fraction == pytest.approx(1.0)

    def test_high_vol_reduces_equity(
        self, scaler: VolatilityScaler, uniform_weights: pd.Series, volatile_prices: pd.DataFrame,
    ) -> None:
        """When realized vol > target, equity_fraction < 1.0."""
        config = VolScalingConfig(target_annual=0.05, lookback_days=63)
        scaled, result = scaler.scale(uniform_weights, volatile_prices, config)
        assert result.scale_factor < 1.0
        assert result.equity_fraction < 1.0
        assert result.equity_fraction == pytest.approx(float(scaled.sum()))

    def test_low_vol_capped_at_cap(
        self, scaler: VolatilityScaler, uniform_weights: pd.Series, low_vol_prices: pd.DataFrame,
    ) -> None:
        """Very low realized vol produces scale_factor = cap, equity = 1.0."""
        config = VolScalingConfig(target_annual=0.15, cap=1.5, lookback_days=63)
        scaled, result = scaler.scale(uniform_weights, low_vol_prices, config)
        assert result.scale_factor == pytest.approx(1.5)
        # equity_fraction = min(1.5, 1.0) = 1.0
        assert result.equity_fraction == pytest.approx(1.0)
        assert result.equity_fraction == pytest.approx(float(scaled.sum()))

    def test_zero_vol_returns_cap(
        self, scaler: VolatilityScaler, uniform_weights: pd.Series, constant_prices: pd.DataFrame,
    ) -> None:
        """Constant prices → zero realized vol → scale_factor = cap."""
        config = VolScalingConfig(target_annual=0.15, cap=1.5, lookback_days=63)
        scaled, result = scaler.scale(uniform_weights, constant_prices, config)
        assert result.scale_factor == pytest.approx(1.5)
        assert result.equity_fraction == pytest.approx(1.0)

    def test_insufficient_history_returns_cap(
        self,
        scaler: VolatilityScaler,
        uniform_weights: pd.Series,
        insufficient_prices: pd.DataFrame,
    ) -> None:
        """Fewer than 21 bars → NaN vol → defaults to cap."""
        config = VolScalingConfig(target_annual=0.15, cap=1.5, lookback_days=63)
        scaled, result = scaler.scale(uniform_weights, insufficient_prices, config)
        assert result.scale_factor == pytest.approx(1.5)

    def test_empty_weights(
        self, scaler: VolatilityScaler, volatile_prices: pd.DataFrame,
    ) -> None:
        """Empty weights returns empty Series and scale_factor = cap."""
        config = VolScalingConfig()
        empty = pd.Series(dtype=float)
        scaled, result = scaler.scale(empty, volatile_prices, config)
        assert scaled.empty
        assert result.scale_factor == pytest.approx(config.cap)
        assert result.equity_fraction == pytest.approx(config.cap)

    def test_single_asset(
        self, scaler: VolatilityScaler, single_asset_prices: pd.DataFrame,
    ) -> None:
        """Single-asset portfolio scales correctly."""
        config = VolScalingConfig(target_annual=0.15, lookback_days=63)
        weights = pd.Series(1.0, index=["A"], dtype=float)
        scaled, result = scaler.scale(weights, single_asset_prices, config)
        assert len(scaled) == 1
        assert scaled.index[0] == "A"
        assert result.equity_fraction == pytest.approx(float(scaled.sum()))
        assert 0.0 <= result.equity_fraction <= 1.0

    def test_floor_enforced(
        self, scaler: VolatilityScaler, uniform_weights: pd.Series, volatile_prices: pd.DataFrame,
    ) -> None:
        """High vol with floor=0.3 → scale_factor never drops below 0.3."""
        config = VolScalingConfig(
            target_annual=0.05,  # very low target → scale will be small
            floor=0.3,
            lookback_days=63,
        )
        _, result = scaler.scale(uniform_weights, volatile_prices, config)
        assert result.scale_factor >= 0.3

    def test_equity_fraction_capped_at_one(
        self, scaler: VolatilityScaler, uniform_weights: pd.Series, low_vol_prices: pd.DataFrame,
    ) -> None:
        """Even when scale_factor > 1.0, equity_fraction never exceeds 1.0."""
        config = VolScalingConfig(target_annual=0.15, cap=2.0, lookback_days=63)
        _, result = scaler.scale(uniform_weights, low_vol_prices, config)
        assert result.equity_fraction <= 1.0

    def test_scaled_weights_sum_to_equity_fraction(
        self, scaler: VolatilityScaler, uniform_weights: pd.Series, volatile_prices: pd.DataFrame,
    ) -> None:
        """Invariant: sum(scaled_weights) == result.equity_fraction."""
        config = VolScalingConfig(target_annual=0.15, lookback_days=63)
        scaled, result = scaler.scale(uniform_weights, volatile_prices, config)
        assert float(scaled.sum()) == pytest.approx(result.equity_fraction)

    def test_concentrated_weights_scale_correctly(
        self,
        scaler: VolatilityScaler,
        concentrated_weights: pd.Series,
        volatile_prices: pd.DataFrame,
    ) -> None:
        """Skewed weights preserve relative proportions after scaling."""
        config = VolScalingConfig(target_annual=0.15, lookback_days=63)
        scaled, result = scaler.scale(concentrated_weights, volatile_prices, config)
        # Relative proportions preserved
        ratios_before = concentrated_weights / concentrated_weights.sum()
        ratios_after = scaled / scaled.sum()
        pd.testing.assert_series_equal(ratios_before, ratios_after, check_exact=False, rtol=1e-9)

    def test_missing_symbol_in_prices(
        self, scaler: VolatilityScaler, volatile_prices: pd.DataFrame,
    ) -> None:
        """Symbol in weights but not in prices is excluded gracefully."""
        weights = pd.Series(
            [0.2, 0.2, 0.2, 0.2, 0.2],
            index=["A", "B", "C", "D", "UNKNOWN"],
            dtype=float,
        )
        config = VolScalingConfig(target_annual=0.15, lookback_days=63)
        scaled, result = scaler.scale(weights, volatile_prices, config)
        assert "UNKNOWN" in scaled.index
        assert result.equity_fraction <= 1.0

    def test_regime_aware_noop(
        self, scaler: VolatilityScaler, uniform_weights: pd.Series, volatile_prices: pd.DataFrame,
    ) -> None:
        """regime_aware=True does not crash (behaviour deferred to Phase 4.6)."""
        config = VolScalingConfig(regime_aware=True)
        scaled, result = scaler.scale(uniform_weights, volatile_prices, config)
        assert not scaled.empty
        assert result.equity_fraction <= 1.0

    def test_all_zero_weights(
        self, scaler: VolatilityScaler, volatile_prices: pd.DataFrame,
    ) -> None:
        """All-zero weights still produce valid result (NaN vol → cap fallback)."""
        weights = pd.Series(0.0, index=["A", "B", "C", "D", "E"], dtype=float)
        config = VolScalingConfig()
        scaled, result = scaler.scale(weights, volatile_prices, config)
        # _compute_realized_vol returns NaN when w_sum <= 0, so scale_factor = cap
        assert result.scale_factor == pytest.approx(config.cap)
        # But equity_fraction = min(cap, 1.0) = 1.0, scaled weights = 0 * 1.0 = 0
        assert result.equity_fraction == pytest.approx(1.0)


class TestComputeRealizedVol:
    def test_known_vol_from_synthetic_data(self, scaler: VolatilityScaler) -> None:
        """Portfolio vol computed via dot product matches approximate expectation."""
        rng = np.random.default_rng(42)
        dates = pd.date_range("2023-01-01", periods=126, freq="B", tz=TZ)
        # Asset A: 20% annualized vol, Asset B: 40% annualized vol
        daily_a = rng.normal(0.0005, 0.20 / math.sqrt(252), len(dates))
        daily_b = rng.normal(0.0005, 0.40 / math.sqrt(252), len(dates))
        prices = pd.DataFrame(
            {"A": 100.0 * np.exp(np.cumsum(daily_a)),
             "B": 100.0 * np.exp(np.cumsum(daily_b))},
            index=dates,
        )
        weights = pd.Series([0.5, 0.5], index=["A", "B"], dtype=float)
        vol = VolatilityScaler._compute_realized_vol(weights, prices, 63)
        # Equal-weight portfolio of 20% and 40% vol assets should be 25-35%
        assert 0.20 <= vol <= 0.35

    def test_insufficient_data_returns_nan(self, scaler: VolatilityScaler) -> None:
        """Fewer than 21 observations returns NaN."""
        dates = pd.date_range("2023-01-01", periods=15, freq="B", tz=TZ)
        prices = pd.DataFrame({"A": [100.0 + i for i in range(15)]}, index=dates)
        weights = pd.Series(1.0, index=["A"], dtype=float)
        vol = VolatilityScaler._compute_realized_vol(weights, prices, 63)
        assert math.isnan(vol)
