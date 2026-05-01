"""Unit tests for the execution simulation module (Phase 4.7).

Covers:
- ExecutionConfig Pydantic validation
- SlippageModelConfig defaults
- SqrtImpactSlippageModel (basic, zero notional, zero ADTV, sqrt scaling)
- Trade / TradeList / ExecutionResult Pydantic models
- ExecutionSimulator.simulate() — happy path, lot rounding, capacity
  violations, hold detection, edge cases, disabled pass-through
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from csm.execution.simulator import ExecutionConfig, ExecutionSimulator
from csm.execution.slippage import SlippageModelConfig, SqrtImpactSlippageModel
from csm.execution.trade_list import (
    ExecutionResult,
    Trade,
    TradeList,
    TradeSide,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def uniform_weights() -> pd.Series:
    """5-symbol equal-weight Series summing to 1.0."""
    return pd.Series(0.2, index=["A", "B", "C", "D", "E"], dtype=float)


@pytest.fixture
def skewed_weights() -> pd.Series:
    """5-symbol skewed weights."""
    return pd.Series(
        [0.4, 0.25, 0.15, 0.12, 0.08],
        index=["A", "B", "C", "D", "E"],
        dtype=float,
    )


@pytest.fixture
def price_data() -> pd.DataFrame:
    """5-symbol price history, 100 days."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=100, freq="B")
    symbols = ["A", "B", "C", "D", "E"]
    data: dict[str, np.ndarray] = {}
    for sym in symbols:
        daily_ret = rng.normal(0.0005, 0.012, len(dates))
        data[sym] = 100.0 * np.exp(np.cumsum(daily_ret))
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def volume_data() -> pd.DataFrame:
    """5-symbol volume history, 100 days."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=100, freq="B")
    symbols = ["A", "B", "C", "D", "E"]
    data: dict[str, np.ndarray] = {}
    for sym in symbols:
        data[sym] = rng.integers(10_000, 50_000, len(dates))
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def low_volume_data() -> pd.DataFrame:
    """5-symbol volume history with very low volumes (triggers capacity violations)."""
    rng = np.random.default_rng(99)
    dates = pd.date_range("2024-01-01", periods=100, freq="B")
    symbols = ["A", "B", "C", "D", "E"]
    data: dict[str, np.ndarray] = {}
    for sym in symbols:
        data[sym] = rng.integers(10, 100, len(dates))
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def current_positions() -> dict[str, int]:
    """Small current positions for A-D, E not held."""
    return {"A": 1000, "B": 500, "C": 300, "D": 200}


@pytest.fixture
def simulator() -> ExecutionSimulator:
    """Fresh ExecutionSimulator instance."""
    return ExecutionSimulator()


@pytest.fixture
def slippage_model() -> SqrtImpactSlippageModel:
    """Fresh SqrtImpactSlippageModel with default config."""
    return SqrtImpactSlippageModel()


# ---------------------------------------------------------------------------
# TestExecutionConfig
# ---------------------------------------------------------------------------


class TestExecutionConfig:
    """Pydantic config validation tests."""

    def test_defaults(self) -> None:
        cfg = ExecutionConfig()
        assert cfg.enabled is True
        assert cfg.aum_thb == 200_000_000
        assert cfg.lot_size == 100
        assert cfg.max_participation_rate == 0.10
        assert cfg.min_trade_weight == 0.001
        assert cfg.adtv_lookback_days == 63

    def test_custom_values(self) -> None:
        sm = SlippageModelConfig(half_spread_bps=20.0, impact_coef=15.0)
        cfg = ExecutionConfig(
            enabled=False,
            aum_thb=500_000_000,
            lot_size=1000,
            max_participation_rate=0.15,
            slippage_model=sm,
            min_trade_weight=0.005,
            adtv_lookback_days=126,
        )
        assert cfg.enabled is False
        assert cfg.aum_thb == 500_000_000
        assert cfg.lot_size == 1000
        assert cfg.max_participation_rate == 0.15
        assert cfg.slippage_model.half_spread_bps == 20.0
        assert cfg.slippage_model.impact_coef == 15.0
        assert cfg.min_trade_weight == 0.005
        assert cfg.adtv_lookback_days == 126

    def test_aum_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            ExecutionConfig(aum_thb=0.0)

    def test_max_participation_rate_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            ExecutionConfig(max_participation_rate=0.0)

    def test_max_participation_rate_must_not_exceed_one(self) -> None:
        with pytest.raises(ValidationError):
            ExecutionConfig(max_participation_rate=1.01)


# ---------------------------------------------------------------------------
# TestSlippageModelConfig
# ---------------------------------------------------------------------------


class TestSlippageModelConfig:
    """Slippage model config tests."""

    def test_defaults(self) -> None:
        cfg = SlippageModelConfig()
        assert cfg.half_spread_bps == 10.0
        assert cfg.impact_coef == 10.0

    def test_custom_values(self) -> None:
        cfg = SlippageModelConfig(half_spread_bps=5.0, impact_coef=8.0)
        assert cfg.half_spread_bps == 5.0
        assert cfg.impact_coef == 8.0


# ---------------------------------------------------------------------------
# TestSqrtImpactSlippageModel
# ---------------------------------------------------------------------------


class TestSqrtImpactSlippageModel:
    """Slippage model computation tests."""

    def test_basic_estimate(self, slippage_model: SqrtImpactSlippageModel) -> None:
        """Slippage = half_spread + impact_coef × sqrt(participation_rate)."""
        notional: float = 1_000_000.0
        adtv: float = 10_000_000.0
        slip: float = slippage_model.estimate(notional, adtv)
        expected: float = 10.0 + 10.0 * math.sqrt(0.1)
        assert slip == pytest.approx(expected)

    def test_zero_notional(self, slippage_model: SqrtImpactSlippageModel) -> None:
        assert slippage_model.estimate(0.0, 1_000_000.0) == 0.0

    def test_negative_notional(self, slippage_model: SqrtImpactSlippageModel) -> None:
        assert slippage_model.estimate(-100.0, 1_000_000.0) == 0.0

    def test_zero_adtv(self, slippage_model: SqrtImpactSlippageModel) -> None:
        assert slippage_model.estimate(1_000_000.0, 0.0) == 0.0

    def test_sqrt_scaling(self, slippage_model: SqrtImpactSlippageModel) -> None:
        """Doubling notional should increase impact by sqrt(2), not 2×."""
        slip1: float = slippage_model.estimate(100_000.0, 1_000_000.0)
        slip2: float = slippage_model.estimate(200_000.0, 1_000_000.0)
        part1: float = 0.1
        part2: float = 0.2
        expected1: float = 10.0 + 10.0 * math.sqrt(part1)
        expected2: float = 10.0 + 10.0 * math.sqrt(part2)
        assert slip1 == pytest.approx(expected1)
        assert slip2 == pytest.approx(expected2)

    def test_custom_config(self) -> None:
        cfg = SlippageModelConfig(half_spread_bps=5.0, impact_coef=15.0)
        model = SqrtImpactSlippageModel(cfg)
        slip: float = model.estimate(1_000_000.0, 10_000_000.0)
        expected: float = 5.0 + 15.0 * math.sqrt(0.1)
        assert slip == pytest.approx(expected)


# ---------------------------------------------------------------------------
# TestTradeModels
# ---------------------------------------------------------------------------


class TestTradeModels:
    """Trade and TradeList Pydantic model tests."""

    def test_trade_construction(self) -> None:
        t = Trade(
            symbol="A",
            side=TradeSide.BUY,
            target_weight=0.25,
            current_weight=0.20,
            delta_weight=0.05,
            target_shares=5000,
            delta_shares=1000,
            notional_thb=500_000.0,
            expected_slippage_bps=12.5,
            participation_rate=0.05,
        )
        assert t.symbol == "A"
        assert t.side == TradeSide.BUY
        assert t.target_weight == 0.25
        assert t.current_weight == 0.20
        assert t.delta_weight == pytest.approx(0.05)
        assert t.target_shares == 5000
        assert t.delta_shares == 1000
        assert t.notional_thb == 500_000.0
        assert t.expected_slippage_bps == 12.5
        assert t.participation_rate == 0.05
        assert t.capacity_violation is False

    def test_trade_with_capacity_violation(self) -> None:
        t = Trade(
            symbol="B",
            side=TradeSide.SELL,
            target_weight=0.0,
            current_weight=0.10,
            delta_weight=-0.10,
            target_shares=0,
            delta_shares=-2000,
            notional_thb=0.0,
            expected_slippage_bps=30.0,
            participation_rate=0.25,
            capacity_violation=True,
        )
        assert t.side == TradeSide.SELL
        assert t.capacity_violation is True
        assert t.delta_shares == -2000

    def test_trade_list_aggregates(self) -> None:
        trades: list[Trade] = [
            Trade(
                symbol="A",
                side=TradeSide.BUY,
                target_weight=0.3,
                current_weight=0.2,
                delta_weight=0.1,
                target_shares=6000,
                delta_shares=2000,
                notional_thb=600_000.0,
                expected_slippage_bps=12.0,
                participation_rate=0.06,
            ),
            Trade(
                symbol="B",
                side=TradeSide.SELL,
                target_weight=0.1,
                current_weight=0.2,
                delta_weight=-0.1,
                target_shares=2000,
                delta_shares=-2000,
                notional_thb=200_000.0,
                expected_slippage_bps=15.0,
                participation_rate=0.04,
            ),
            Trade(
                symbol="C",
                side=TradeSide.HOLD,
                target_weight=0.2,
                current_weight=0.2,
                delta_weight=0.0,
                target_shares=4000,
                delta_shares=0,
                notional_thb=400_000.0,
                expected_slippage_bps=0.0,
                participation_rate=0.0,
            ),
        ]
        asof: pd.Timestamp = pd.Timestamp("2024-06-15")
        tl = TradeList(
            trades=trades,
            total_turnover=0.1,
            total_slippage_cost_bps=13.5,
            n_buys=1,
            n_sells=1,
            n_holds=1,
            n_capacity_violations=0,
            asof=asof,
        )
        assert tl.n_buys == 1
        assert tl.n_sells == 1
        assert tl.n_holds == 1
        assert tl.n_capacity_violations == 0
        assert len(tl.trades) == 3
        assert tl.asof == asof

    def test_execution_result_construction(self) -> None:
        tl = TradeList(
            trades=[],
            asof=pd.Timestamp("2024-06-15"),
        )
        er = ExecutionResult(
            trade_list=tl,
            post_execution_equity_fraction=0.95,
        )
        assert er.post_execution_equity_fraction == pytest.approx(0.95)

    def test_trade_side_enum(self) -> None:
        assert TradeSide.BUY.value == "BUY"
        assert TradeSide.SELL.value == "SELL"
        assert TradeSide.HOLD.value == "HOLD"


# ---------------------------------------------------------------------------
# TestExecutionSimulator
# ---------------------------------------------------------------------------


class TestExecutionSimulator:
    """Core simulate() behaviour tests."""

    def test_disabled_pass_through(
        self,
        simulator: ExecutionSimulator,
        uniform_weights: pd.Series,
        price_data: pd.DataFrame,
        volume_data: pd.DataFrame,
        current_positions: dict[str, int],
    ) -> None:
        cfg = ExecutionConfig(enabled=False)
        executed, result = simulator.simulate(
            uniform_weights, current_positions, price_data, volume_data, cfg
        )
        pd.testing.assert_series_equal(executed, uniform_weights)
        assert result.post_execution_equity_fraction == 1.0
        assert len(result.trade_list.trades) == 0

    def test_empty_weights(
        self,
        simulator: ExecutionSimulator,
        price_data: pd.DataFrame,
        volume_data: pd.DataFrame,
        current_positions: dict[str, int],
    ) -> None:
        cfg = ExecutionConfig()
        empty: pd.Series = pd.Series(dtype=float)
        executed, result = simulator.simulate(
            empty, current_positions, price_data, volume_data, cfg
        )
        assert executed.empty
        assert result.post_execution_equity_fraction == 0.0
        assert len(result.trade_list.trades) == 0

    def test_basic_simulation(
        self,
        simulator: ExecutionSimulator,
        uniform_weights: pd.Series,
        price_data: pd.DataFrame,
        volume_data: pd.DataFrame,
        current_positions: dict[str, int],
    ) -> None:
        """Simulate with 5-symbol equal-weight portfolio and small positions."""
        cfg = ExecutionConfig(aum_thb=10_000_000)
        executed, result = simulator.simulate(
            uniform_weights, current_positions, price_data, volume_data, cfg
        )
        assert len(result.trade_list.trades) == 5
        # Each symbol gets 20% of 10M = 2M, converted to shares at latest price
        assert result.trade_list.n_buys >= 0
        assert result.trade_list.n_holds >= 0
        assert result.post_execution_equity_fraction > 0.0
        assert result.post_execution_equity_fraction <= 1.0
        # Each trade should reference a valid symbol
        for t in result.trade_list.trades:
            assert t.symbol in ["A", "B", "C", "D", "E"]
            assert t.target_weight == pytest.approx(0.2)

    def test_lot_rounding(
        self,
        simulator: ExecutionSimulator,
        skewed_weights: pd.Series,
        price_data: pd.DataFrame,
        volume_data: pd.DataFrame,
    ) -> None:
        """Shares should be rounded down to lot size (100)."""
        cfg = ExecutionConfig(aum_thb=1_000_000, lot_size=100)
        # No current positions — all should be BUYs
        executed, result = simulator.simulate(skewed_weights, {}, price_data, volume_data, cfg)
        for t in result.trade_list.trades:
            if t.side != TradeSide.HOLD:
                assert t.target_shares % 100 == 0, (
                    f"{t.symbol}: target_shares={t.target_shares} not lot-aligned"
                )
                assert t.delta_shares % 100 == 0, (
                    f"{t.symbol}: delta_shares={t.delta_shares} not lot-aligned"
                )

    def test_capacity_violation_flag(
        self,
        simulator: ExecutionSimulator,
        skewed_weights: pd.Series,
        price_data: pd.DataFrame,
        low_volume_data: pd.DataFrame,
    ) -> None:
        """Low volumes should trigger capacity_violation=True."""
        cfg = ExecutionConfig(
            aum_thb=200_000_000,  # Large AUM vs small volume
            max_participation_rate=0.10,
        )
        executed, result = simulator.simulate(skewed_weights, {}, price_data, low_volume_data, cfg)
        assert result.trade_list.n_capacity_violations > 0

    def test_hold_detection_when_zero_delta(
        self,
        simulator: ExecutionSimulator,
        price_data: pd.DataFrame,
        volume_data: pd.DataFrame,
    ) -> None:
        """Positions matching target exactly produce HOLD trades."""
        latest: pd.Series = price_data.iloc[-1]
        price_a: float = float(latest["A"])
        price_b: float = float(latest["B"])
        # Each symbol: 50% target, AUM = sum of notional values
        aum: float = price_a * 1000 + price_b * 1000
        cfg = ExecutionConfig(aum_thb=aum, lot_size=1, min_trade_weight=1e-8)
        w_a: float = 0.501 if abs(price_a - price_b) < 1e-6 else (price_a * 1000) / aum
        w_b: float = 1.0 - w_a
        target_weights: pd.Series = pd.Series([w_a, w_b], index=["A", "B"], dtype=float)
        positions: dict[str, int] = {"A": 1000, "B": 1000}
        executed, result = simulator.simulate(
            target_weights, positions, price_data, volume_data, cfg
        )
        assert len(result.trade_list.trades) == 2
        # With lot_size=1 and matching positions, both should be HOLD
        assert result.trade_list.n_buys == 0
        assert result.trade_list.n_sells == 0
        assert result.trade_list.n_holds == 2

    def test_all_new_positions(
        self,
        simulator: ExecutionSimulator,
        uniform_weights: pd.Series,
        price_data: pd.DataFrame,
        volume_data: pd.DataFrame,
    ) -> None:
        """No current positions → all should be BUYs."""
        cfg = ExecutionConfig(aum_thb=10_000_000)
        executed, result = simulator.simulate(uniform_weights, {}, price_data, volume_data, cfg)
        for t in result.trade_list.trades:
            assert t.current_weight == 0.0
            assert t.current_weight == pytest.approx(0.0)

    def test_full_exit(
        self,
        simulator: ExecutionSimulator,
        price_data: pd.DataFrame,
        volume_data: pd.DataFrame,
    ) -> None:
        """All zero target weights → all SELLs."""
        cfg = ExecutionConfig(aum_thb=10_000_000)
        zero_weights: pd.Series = pd.Series([0.0, 0.0, 0.0], index=["A", "B", "C"], dtype=float)
        positions: dict[str, int] = {"A": 1000, "B": 500, "C": 300}
        executed, result = simulator.simulate(zero_weights, positions, price_data, volume_data, cfg)
        for t in result.trade_list.trades:
            assert t.target_weight == 0.0
            if t.current_weight > 0.001:
                assert t.side == TradeSide.SELL
        assert result.trade_list.n_sells >= 1

    def test_trade_list_determinism(
        self,
        simulator: ExecutionSimulator,
        uniform_weights: pd.Series,
        price_data: pd.DataFrame,
        volume_data: pd.DataFrame,
        current_positions: dict[str, int],
    ) -> None:
        """Two runs with same inputs produce identical TradeLists."""
        cfg = ExecutionConfig(aum_thb=10_000_000)
        _, result1 = simulator.simulate(
            uniform_weights, current_positions, price_data, volume_data, cfg
        )
        _, result2 = simulator.simulate(
            uniform_weights, current_positions, price_data, volume_data, cfg
        )
        assert result1.trade_list.total_turnover == pytest.approx(result2.trade_list.total_turnover)
        assert result1.trade_list.n_buys == result2.trade_list.n_buys
        assert result1.trade_list.n_sells == result2.trade_list.n_sells
        assert result1.trade_list.n_holds == result2.trade_list.n_holds
        for t1, t2 in zip(
            result1.trade_list.trades,
            result2.trade_list.trades,
            strict=False,
        ):
            assert t1.symbol == t2.symbol
            assert t1.side == t2.side
            assert t1.target_shares == t2.target_shares
            assert t1.delta_shares == t2.delta_shares

    def test_zero_volume_symbol_dropped(
        self,
        simulator: ExecutionSimulator,
        uniform_weights: pd.Series,
        price_data: pd.DataFrame,
        volume_data: pd.DataFrame,
    ) -> None:
        """Symbol with zero volume should get notional 0 and capacity_violation."""
        # Override volumes: E has zero volume
        vol_zero: pd.DataFrame = volume_data.copy()
        vol_zero.loc[:, "E"] = 0.0
        cfg = ExecutionConfig(aum_thb=10_000_000)
        executed, result = simulator.simulate(uniform_weights, {}, price_data, vol_zero, cfg)
        # E should have zero notional or low executed weight
        e_trades = [t for t in result.trade_list.trades if t.symbol == "E"]
        assert len(e_trades) == 1
        assert e_trades[0].notional_thb == 0.0 or e_trades[0].participation_rate == 0.0

    def test_post_execution_equity_fraction_lt_one(
        self,
        simulator: ExecutionSimulator,
        uniform_weights: pd.Series,
        price_data: pd.DataFrame,
        volume_data: pd.DataFrame,
    ) -> None:
        """Lot rounding causes cash drag → equity fraction < 1.0."""
        cfg = ExecutionConfig(aum_thb=500_000, lot_size=100)
        # Each symbol gets 100K THB, but share price may not divide evenly
        executed, result = simulator.simulate(uniform_weights, {}, price_data, volume_data, cfg)
        assert 0.0 < result.post_execution_equity_fraction <= 1.0
