"""Unit tests for the liquidity and capacity overlay."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from csm.portfolio.liquidity_overlay import (
    LiquidityConfig,
    LiquidityOverlay,
    LiquidityResult,
    PositionLiquidityInfo,
    compute_capacity_curve,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def uniform_weights() -> pd.Series:
    """5-symbol equal-weight Series summing to 1.0."""
    return pd.Series(
        [0.2, 0.2, 0.2, 0.2, 0.2],
        index=["A", "B", "C", "D", "E"],
        dtype=float,
    )


@pytest.fixture
def skewed_weights() -> pd.Series:
    """5-symbol skewed weights summing to 1.0."""
    return pd.Series(
        [0.50, 0.25, 0.15, 0.07, 0.03],
        index=["A", "B", "C", "D", "E"],
        dtype=float,
    )


@pytest.fixture
def price_data() -> pd.DataFrame:
    """200 bars of synthetic close prices at ~100 THB."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=200, freq="B")
    data: dict[str, np.ndarray] = {}
    base_prices: dict[str, float] = {
        "A": 100.0, "B": 50.0, "C": 200.0, "D": 30.0, "E": 80.0,
    }
    for sym, base in base_prices.items():
        returns = rng.normal(0.0005, 0.02, size=200)
        data[sym] = base * np.exp(np.cumsum(returns))
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def high_volume_data() -> pd.DataFrame:
    """200 bars of synthetic volumes — high enough to never cap."""
    rng = np.random.default_rng(99)
    dates = pd.date_range("2024-01-01", periods=200, freq="B")
    data: dict[str, np.ndarray] = {}
    for sym in ["A", "B", "C", "D", "E"]:
        data[sym] = rng.uniform(50_000_000, 100_000_000, size=200)
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def low_volume_data() -> pd.DataFrame:
    """200 bars of synthetic volumes — low enough to cap at 200M AUM."""
    rng = np.random.default_rng(77)
    dates = pd.date_range("2024-01-01", periods=200, freq="B")
    data: dict[str, np.ndarray] = {}
    for sym in ["A", "B", "C", "D", "E"]:
        data[sym] = rng.uniform(100_000, 500_000, size=200)
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def overlay() -> LiquidityOverlay:
    """Fresh LiquidityOverlay instance."""
    return LiquidityOverlay()


# ---------------------------------------------------------------------------
# TestLiquidityConfig
# ---------------------------------------------------------------------------


class TestLiquidityConfig:
    """Configuration validation tests."""

    def test_defaults(self) -> None:
        cfg = LiquidityConfig()
        assert cfg.enabled is True
        assert cfg.adv_cap_pct == 0.10
        assert cfg.adtv_lookback_days == 63
        assert cfg.assumed_aum_thb == 200_000_000

    def test_custom_values(self) -> None:
        cfg = LiquidityConfig(
            enabled=False,
            adv_cap_pct=0.15,
            adtv_lookback_days=126,
            assumed_aum_thb=500_000_000,
        )
        assert cfg.enabled is False
        assert cfg.adv_cap_pct == 0.15
        assert cfg.adtv_lookback_days == 126
        assert cfg.assumed_aum_thb == 500_000_000

    def test_adv_cap_pct_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            LiquidityConfig(adv_cap_pct=0.0)

    def test_adv_cap_pct_must_not_exceed_one(self) -> None:
        with pytest.raises(ValidationError):
            LiquidityConfig(adv_cap_pct=1.01)

    def test_lookback_minimum(self) -> None:
        with pytest.raises(ValidationError):
            LiquidityConfig(adtv_lookback_days=20)


# ---------------------------------------------------------------------------
# TestLiquidityResult
# ---------------------------------------------------------------------------


class TestLiquidityResult:
    """Result model tests."""

    def test_construction(self) -> None:
        result = LiquidityResult(
            effective_equity_fraction=1.0,
            n_capped=0,
            n_total=5,
            n_zero_adtv=0,
            per_position={},
            total_target_notional=200_000_000.0,
            total_capped_notional=200_000_000.0,
        )
        assert result.effective_equity_fraction == 1.0
        assert result.n_capped == 0


# ---------------------------------------------------------------------------
# TestPositionLiquidityInfo
# ---------------------------------------------------------------------------


class TestPositionLiquidityInfo:
    """Per-position info model tests."""

    def test_cap_binding_position(self) -> None:
        info = PositionLiquidityInfo(
            symbol="A",
            adtv_thb=5_000_000.0,
            target_notional=10_000_000.0,
            capped_notional=500_000.0,
            original_weight=0.2,
            adjusted_weight=0.01,
            participation_rate=2.0,
            cap_binding=True,
        )
        assert info.cap_binding is True
        assert info.participation_rate > 0.10

    def test_non_binding_position(self) -> None:
        info = PositionLiquidityInfo(
            symbol="B",
            adtv_thb=100_000_000.0,
            target_notional=5_000_000.0,
            capped_notional=5_000_000.0,
            original_weight=0.2,
            adjusted_weight=0.2,
            participation_rate=0.05,
            cap_binding=False,
        )
        assert info.cap_binding is False


# ---------------------------------------------------------------------------
# TestLiquidityOverlay
# ---------------------------------------------------------------------------


class TestLiquidityOverlay:
    """Core overlay behaviour tests."""

    def test_disabled_pass_through(
        self, overlay: LiquidityOverlay, uniform_weights: pd.Series,
        price_data: pd.DataFrame, high_volume_data: pd.DataFrame,
    ) -> None:
        """Disabled overlay returns weights unchanged."""
        cfg = LiquidityConfig(enabled=False)
        adj, result = overlay.apply(
            uniform_weights, price_data, high_volume_data, cfg,
        )
        pd.testing.assert_series_equal(adj, uniform_weights)
        assert result.effective_equity_fraction == pytest.approx(1.0)
        assert result.n_capped == 0
        assert result.n_total == 5

    def test_empty_weights(
        self, overlay: LiquidityOverlay,
        price_data: pd.DataFrame, high_volume_data: pd.DataFrame,
    ) -> None:
        """Empty weights produce empty result."""
        empty = pd.Series(dtype=float)
        adj, result = overlay.apply(
            empty, price_data, high_volume_data, LiquidityConfig(),
        )
        assert adj.empty
        assert result.n_total == 0
        assert result.effective_equity_fraction == 0.0

    def test_no_cap_binding_at_high_volume(
        self, overlay: LiquidityOverlay, uniform_weights: pd.Series,
        price_data: pd.DataFrame, high_volume_data: pd.DataFrame,
    ) -> None:
        """High-volume data → no positions capped, equity fraction = 1.0."""
        adj, result = overlay.apply(
            uniform_weights, price_data, high_volume_data, LiquidityConfig(),
        )
        assert result.n_capped == 0
        assert result.n_zero_adtv == 0
        assert result.effective_equity_fraction == pytest.approx(1.0)
        for info in result.per_position.values():
            assert info.cap_binding is False
            assert info.adjusted_weight == pytest.approx(info.original_weight)

    def test_cap_binds_at_low_volume(
        self, overlay: LiquidityOverlay, uniform_weights: pd.Series,
        price_data: pd.DataFrame, low_volume_data: pd.DataFrame,
    ) -> None:
        """Low-volume data → positions are capped, equity fraction < 1.0."""
        cfg = LiquidityConfig(assumed_aum_thb=200_000_000)
        adj, result = overlay.apply(
            uniform_weights, price_data, low_volume_data, cfg,
        )
        assert result.n_capped > 0
        assert result.effective_equity_fraction < 1.0
        # Each capped position's adjusted weight must be ≤ original weight
        for info in result.per_position.values():
            assert info.adjusted_weight <= info.original_weight + 1e-12

    def test_all_positions_capped_at_extreme_aum(
        self, overlay: LiquidityOverlay, uniform_weights: pd.Series,
        price_data: pd.DataFrame, low_volume_data: pd.DataFrame,
    ) -> None:
        """Extreme AUM → every position capped."""
        cfg = LiquidityConfig(assumed_aum_thb=1_000_000_000_000)
        adj, result = overlay.apply(
            uniform_weights, price_data, low_volume_data, cfg,
        )
        assert result.n_capped == len(uniform_weights)
        assert result.effective_equity_fraction < 0.01

    def test_zero_advt_symbols_weight_zeroed(
        self, overlay: LiquidityOverlay,
        price_data: pd.DataFrame,
    ) -> None:
        """Symbol with zero volume → weight zeroed, logged as zero_adtv."""
        weights = pd.Series([0.5, 0.5], index=["A", "B"], dtype=float)
        dates = pd.date_range("2024-01-01", periods=200, freq="B")
        # B has all-zero volume
        volumes = pd.DataFrame(
            {"A": np.full(200, 1_000_000.0), "B": np.zeros(200)},
            index=dates,
        )
        adj, result = overlay.apply(
            weights, price_data[["A", "B"]], volumes, LiquidityConfig(),
        )
        assert result.n_zero_adtv == 1
        assert result.per_position["B"].cap_binding is True
        assert result.per_position["B"].adjusted_weight == 0.0
        assert math.isinf(result.per_position["B"].participation_rate)
        # A should be uncapped
        assert result.per_position["A"].adjusted_weight > 0.0

    def test_adtv_computation_matches_manual(
        self, overlay: LiquidityOverlay,
        price_data: pd.DataFrame, high_volume_data: pd.DataFrame,
    ) -> None:
        """_compute_adtv matches manual mean(close × volume)."""
        adtv = overlay._compute_adtv(price_data, high_volume_data, 63)
        # Manual check for symbol A
        close = price_data["A"].tail(63)
        vol = high_volume_data["A"].tail(63)
        min_len = min(len(close), len(vol))
        expected = float((close.iloc[-min_len:] * vol.iloc[-min_len:]).mean())
        assert adtv["A"] == pytest.approx(expected)

    def test_weights_sum_to_equity_fraction(
        self, overlay: LiquidityOverlay, skewed_weights: pd.Series,
        price_data: pd.DataFrame, low_volume_data: pd.DataFrame,
    ) -> None:
        """Adjusted weights sum to result.effective_equity_fraction."""
        adj, result = overlay.apply(
            skewed_weights, price_data, low_volume_data, LiquidityConfig(),
        )
        assert float(adj.sum()) == pytest.approx(result.effective_equity_fraction)

    def test_disabled_preserves_weight_sum(
        self, overlay: LiquidityOverlay, skewed_weights: pd.Series,
        price_data: pd.DataFrame, low_volume_data: pd.DataFrame,
    ) -> None:
        """Disabled overlay preserves original weight sum."""
        cfg = LiquidityConfig(enabled=False)
        adj, result = overlay.apply(
            skewed_weights, price_data, low_volume_data, cfg,
        )
        assert float(adj.sum()) == pytest.approx(float(skewed_weights.sum()))

    def test_single_position(
        self, overlay: LiquidityOverlay,
        price_data: pd.DataFrame, high_volume_data: pd.DataFrame,
    ) -> None:
        """Single-asset portfolio."""
        weights = pd.Series([1.0], index=["A"], dtype=float)
        adj, result = overlay.apply(
            weights, price_data, high_volume_data, LiquidityConfig(),
        )
        assert len(adj) == 1
        assert result.n_total == 1
        assert "A" in result.per_position

    def test_symbol_missing_from_volumes(
        self, overlay: LiquidityOverlay, uniform_weights: pd.Series,
        price_data: pd.DataFrame, high_volume_data: pd.DataFrame,
    ) -> None:
        """Symbol in weights but missing from volumes → zero ADTV, weight zeroed."""
        vols = high_volume_data.drop(columns=["E"])
        adj, result = overlay.apply(
            uniform_weights, price_data, vols, LiquidityConfig(),
        )
        assert result.n_zero_adtv >= 1
        info = result.per_position["E"]
        assert info.adtv_thb == 0.0
        assert info.adjusted_weight == 0.0

    def test_symbol_missing_from_prices(
        self, overlay: LiquidityOverlay, uniform_weights: pd.Series,
        price_data: pd.DataFrame, high_volume_data: pd.DataFrame,
    ) -> None:
        """Symbol in weights but missing from prices → zero ADTV, weight zeroed."""
        prices = price_data.drop(columns=["C"])
        adj, result = overlay.apply(
            uniform_weights, prices, high_volume_data, LiquidityConfig(),
        )
        assert result.n_zero_adtv >= 1
        info = result.per_position["C"]
        assert info.adtv_thb == 0.0
        assert info.adjusted_weight == 0.0

    def test_zero_weight_symbols_skipped(
        self, overlay: LiquidityOverlay,
        price_data: pd.DataFrame, high_volume_data: pd.DataFrame,
    ) -> None:
        """Zero-weight entries are passed through as zero."""
        weights = pd.Series([0.5, 0.5, 0.0], index=["A", "B", "C"], dtype=float)
        adj, result = overlay.apply(
            weights, price_data, high_volume_data, LiquidityConfig(),
        )
        assert adj["C"] == 0.0
        assert result.n_total == 3

    def test_short_but_sufficient_history(
        self, overlay: LiquidityOverlay, uniform_weights: pd.Series,
    ) -> None:
        """63-bar lookback works when exactly 63 bars available."""
        dates = pd.date_range("2024-01-01", periods=63, freq="B")
        rng = np.random.default_rng(123)
        prices = pd.DataFrame(
            {sym: rng.uniform(90, 110, size=63) for sym in uniform_weights.index},
            index=dates,
        )
        volumes = pd.DataFrame(
            {sym: rng.uniform(1_000_000, 2_000_000, size=63) for sym in uniform_weights.index},
            index=dates,
        )
        adj, result = overlay.apply(
            uniform_weights, prices, volumes, LiquidityConfig(assumed_aum_thb=1_000_000),
        )
        assert result.n_total == 5
        # At 1M AUM with ~1.5M ADTV, 20% weight = 200k notional, or ~13% participation
        # Some may be capped at 10%, some not
        assert result.n_zero_adtv == 0


# ---------------------------------------------------------------------------
# TestComputeCapacityCurve
# ---------------------------------------------------------------------------


class TestComputeCapacityCurve:
    """Capacity curve tests."""

    def test_curve_has_expected_columns(
        self, uniform_weights: pd.Series,
        price_data: pd.DataFrame, high_volume_data: pd.DataFrame,
    ) -> None:
        """Capacity curve returns DataFrame with correct columns."""
        curve = compute_capacity_curve(
            uniform_weights, price_data, high_volume_data,
            aum_grid=[10_000_000, 100_000_000, 1_000_000_000],
        )
        expected_cols = [
            "aum_thb", "n_capped", "fraction_capped",
            "effective_equity_fraction", "max_participation_rate",
        ]
        for col in expected_cols:
            assert col in curve.columns
        assert len(curve) == 3

    def test_curve_n_capped_monotonic_in_aum(
        self, uniform_weights: pd.Series,
        price_data: pd.DataFrame, low_volume_data: pd.DataFrame,
    ) -> None:
        """As AUM increases, n_capped is non-decreasing."""
        curve = compute_capacity_curve(
            uniform_weights, price_data, low_volume_data,
            aum_grid=[
                1_000_000, 10_000_000, 50_000_000,
                100_000_000, 500_000_000, 1_000_000_000,
            ],
        )
        n_capped = curve["n_capped"].to_numpy()
        assert np.all(np.diff(n_capped) >= 0), f"n_capped not monotonic: {n_capped.tolist()}"

    def test_curve_equity_fraction_decreasing_in_aum(
        self, uniform_weights: pd.Series,
        price_data: pd.DataFrame, low_volume_data: pd.DataFrame,
    ) -> None:
        """As AUM increases, effective_equity_fraction is non-increasing."""
        curve = compute_capacity_curve(
            uniform_weights, price_data, low_volume_data,
            aum_grid=[10_000_000, 100_000_000, 1_000_000_000],
        )
        ef = curve["effective_equity_fraction"].to_numpy()
        assert np.all(np.diff(ef) <= 1e-12), f"equity fraction not decreasing: {ef.tolist()}"

    def test_curve_at_zero_aum_all_pass(
        self, uniform_weights: pd.Series,
        price_data: pd.DataFrame, high_volume_data: pd.DataFrame,
    ) -> None:
        """At very small AUM, no positions are capped."""
        curve = compute_capacity_curve(
            uniform_weights, price_data, high_volume_data,
            aum_grid=[1_000],  # 1k THB
        )
        assert curve["n_capped"].iloc[0] == 0
        assert curve["effective_equity_fraction"].iloc[0] == pytest.approx(1.0)

    def test_curve_default_grid(self) -> None:
        """Default grid produces 20 points and covers a reasonable range."""
        rng = np.random.default_rng(55)
        dates = pd.date_range("2024-01-01", periods=200, freq="B")
        prices = pd.DataFrame(
            {"X": rng.uniform(90, 110, size=200)}, index=dates,
        )
        volumes = pd.DataFrame(
            {"X": rng.uniform(1_000_000, 2_000_000, size=200)}, index=dates,
        )
        weights = pd.Series([1.0], index=["X"], dtype=float)
        curve = compute_capacity_curve(weights, prices, volumes)
        assert len(curve) == 20
        assert curve["aum_thb"].iloc[0] >= 10_000_000
        assert curve["aum_thb"].iloc[-1] <= 10_000_000_000
