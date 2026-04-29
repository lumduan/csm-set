"""Unit tests for the drawdown circuit breaker."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from csm.portfolio.drawdown_circuit_breaker import (
    CircuitBreakerResult,
    DrawdownCircuitBreaker,
    DrawdownCircuitBreakerConfig,
)
from csm.portfolio.state import CircuitBreakerState

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
def breaker() -> DrawdownCircuitBreaker:
    """Fresh DrawdownCircuitBreaker instance."""
    return DrawdownCircuitBreaker()


@pytest.fixture
def rising_equity() -> pd.Series:
    """100 bars of monotonically increasing equity (rolling DD ≈ 0)."""
    dates = pd.date_range("2024-01-01", periods=100, freq="B")
    values = 100.0 * np.exp(np.cumsum(np.full(100, 0.001)))
    return pd.Series(values, index=dates, dtype=float)


@pytest.fixture
def flat_equity() -> pd.Series:
    """100 bars of flat equity (DD = 0)."""
    dates = pd.date_range("2024-01-01", periods=100, freq="B")
    return pd.Series(100.0, index=dates, dtype=float)


@pytest.fixture
def crash_equity() -> pd.Series:
    """Equity that rises to 130, then crashes 25% to ~97.5.

    Days 1-50: 100 → 130 (rising ~0.5%/day)
    Days 51-70: crash from 130 to 97.5 (≈ -25% from peak)
    Days 71-100: stays flat at 97.5

    Rolling DD at day 70 peaks at about -25%, which exceeds the -20% trigger.
    """
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=100, freq="B")

    values = np.empty(100)
    values[0] = 100.0
    # Rise: days 1-49
    for i in range(1, 50):
        values[i] = values[i - 1] * (1.0 + abs(rng.normal(0.005, 0.01)))
    # Crash: days 50-69 — drop to ~75% of peak
    peak = values[49]
    for i in range(50, 70):
        frac = (i - 50) / 20.0  # 0 → 1 over crash period
        values[i] = peak * (1.0 - 0.25 * frac)
    # Flat: days 70-99
    values[70:] = values[69]
    return pd.Series(values, index=dates, dtype=float)


@pytest.fixture
def recover_equity() -> pd.Series:
    """Equity that crashes, then recovers above -10%.

    Days 1-40: rise 100 → 120
    Days 41-50: crash from 120 to 96 (-20% from peak)
    Days 51-60: stays flat at 96 (DD ≈ -20%)
    Days 61-80: recovers from 96 to 115 (DD ≈ -4.2% from peak 120)
    Days 81-100: stays at 115
    """
    dates = pd.date_range("2024-01-01", periods=100, freq="B")
    values = np.empty(100)
    values[0] = 100.0
    for i in range(1, 40):
        values[i] = values[i - 1] * 1.005
    peak = values[39]  # ≈ 120
    for i in range(40, 50):
        frac = (i - 40) / 10.0
        values[i] = peak * (1.0 - 0.20 * frac)
    values[50:60] = values[49]  # stay at ~96
    for i in range(60, 80):
        frac = (i - 60) / 20.0
        values[i] = peak * (0.80 + 0.15 * frac)  # 80% → 95% of peak
    values[80:] = values[79]  # stay recovered
    return pd.Series(values, index=dates, dtype=float)


@pytest.fixture
def short_equity() -> pd.Series:
    """Only 5 data points (< window_days=60)."""
    dates = pd.date_range("2024-01-01", periods=5, freq="B")
    return pd.Series([100.0, 102.0, 101.0, 103.0, 105.0], index=dates, dtype=float)


@pytest.fixture
def empty_equity() -> pd.Series:
    """Empty equity curve."""
    return pd.Series(dtype=float)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_equity_with_dd(target_dd: float, window: int = 60) -> pd.Series:
    """Build an equity curve whose final rolling DD ≈ *target_dd*.

    The curve rises for *window* days, then drops so the last value
    produces the requested rolling drawdown against the peak.
    """
    dates = pd.date_range("2024-01-01", periods=window + 10, freq="B")
    values = np.linspace(100.0, 200.0, window + 10)
    # Set the last value to create the desired DD from the peak (200)
    peak = 200.0
    target_value = peak * (1.0 + target_dd)
    values[-1] = target_value
    return pd.Series(values, index=dates, dtype=float)


# ---------------------------------------------------------------------------
# TestDrawdownCircuitBreakerConfig
# ---------------------------------------------------------------------------


class TestDrawdownCircuitBreakerConfig:
    """Configuration validation tests."""

    def test_defaults(self) -> None:
        cfg = DrawdownCircuitBreakerConfig()
        assert cfg.enabled is True
        assert cfg.window_days == 60
        assert cfg.trigger_threshold == -0.20
        assert cfg.recovery_threshold == -0.10
        assert cfg.recovery_confirm_days == 21
        assert cfg.safe_mode_max_equity == 0.20

    def test_custom_values(self) -> None:
        cfg = DrawdownCircuitBreakerConfig(
            enabled=False,
            window_days=120,
            trigger_threshold=-0.15,
            recovery_threshold=-0.05,
            recovery_confirm_days=10,
            safe_mode_max_equity=0.30,
        )
        assert cfg.enabled is False
        assert cfg.window_days == 120
        assert cfg.trigger_threshold == -0.15
        assert cfg.recovery_threshold == -0.05

    def test_window_days_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            DrawdownCircuitBreakerConfig(window_days=0)

    def test_trigger_threshold_positive_raises(self) -> None:
        with pytest.raises(ValidationError):
            DrawdownCircuitBreakerConfig(trigger_threshold=0.01)

    def test_recovery_not_greater_than_trigger_raises(self) -> None:
        with pytest.raises(ValueError):
            DrawdownCircuitBreakerConfig(
                trigger_threshold=-0.20,
                recovery_threshold=-0.25,
            )

    def test_safe_mode_equity_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            DrawdownCircuitBreakerConfig(safe_mode_max_equity=0.0)


# ---------------------------------------------------------------------------
# TestCircuitBreakerResult
# ---------------------------------------------------------------------------


class TestCircuitBreakerResult:
    """Result model tests."""

    def test_construction(self) -> None:
        result = CircuitBreakerResult(
            triggered=True,
            current_state="TRIPPED",
            rolling_drawdown=-0.25,
            equity_fraction=0.20,
            recovery_progress_days=0,
            previous_state="NORMAL",
            transitioned=True,
        )
        assert result.triggered is True
        assert result.current_state == "TRIPPED"
        assert result.rolling_drawdown == -0.25
        assert result.equity_fraction == 0.20
        assert result.transitioned is True


# ---------------------------------------------------------------------------
# TestDrawdownCircuitBreaker
# ---------------------------------------------------------------------------


class TestDrawdownCircuitBreaker:
    """Core circuit breaker behaviour tests."""

    def test_disabled_pass_through(
        self,
        breaker: DrawdownCircuitBreaker,
        uniform_weights: pd.Series,
        crash_equity: pd.Series,
    ) -> None:
        """Disabled overlay returns weights unchanged, equity_fraction=1.0."""
        cfg = DrawdownCircuitBreakerConfig(enabled=False)
        adj, result = breaker.apply(uniform_weights, crash_equity, cfg)
        pd.testing.assert_series_equal(adj, uniform_weights)
        assert result.triggered is False
        assert result.current_state == "NORMAL"
        assert result.equity_fraction == pytest.approx(1.0)
        assert result.transitioned is False

    def test_empty_weights(
        self,
        breaker: DrawdownCircuitBreaker,
        rising_equity: pd.Series,
    ) -> None:
        """Empty weights produce empty result."""
        empty = pd.Series(dtype=float)
        adj, result = breaker.apply(empty, rising_equity, DrawdownCircuitBreakerConfig())
        assert adj.empty
        assert result.equity_fraction == 0.0
        assert result.triggered is False

    def test_normal_no_trip_rising_equity(
        self,
        breaker: DrawdownCircuitBreaker,
        uniform_weights: pd.Series,
        rising_equity: pd.Series,
    ) -> None:
        """Rising equity (DD ≈ 0) does not trip the breaker."""
        adj, result = breaker.apply(
            uniform_weights,
            rising_equity,
            DrawdownCircuitBreakerConfig(),
        )
        assert result.current_state == "NORMAL"
        assert result.transitioned is False
        assert result.triggered is False
        assert result.equity_fraction == pytest.approx(1.0)
        # Weights should be unchanged (scaled by 1.0)
        pd.testing.assert_series_equal(adj, uniform_weights)

    def test_normal_to_tripped_on_crash(
        self,
        breaker: DrawdownCircuitBreaker,
        uniform_weights: pd.Series,
        crash_equity: pd.Series,
    ) -> None:
        """Equity crash > 20% triggers NORMAL → TRIPPED."""
        adj, result = breaker.apply(
            uniform_weights,
            crash_equity,
            DrawdownCircuitBreakerConfig(window_days=60),
        )
        assert result.current_state == "TRIPPED"
        assert result.previous_state == "NORMAL"
        assert result.transitioned is True
        assert result.triggered is True
        assert result.equity_fraction == 0.20

    def test_normal_no_trip_when_above_trigger(
        self,
        breaker: DrawdownCircuitBreaker,
        uniform_weights: pd.Series,
    ) -> None:
        """DD at -15% (above -20% trigger) does not trip."""
        equity = _make_equity_with_dd(-0.15)
        adj, result = breaker.apply(
            uniform_weights, equity, DrawdownCircuitBreakerConfig(window_days=60),
        )
        assert result.current_state == "NORMAL"
        assert result.triggered is False

    def test_tripped_stays_tripped_while_below_recovery(
        self,
        breaker: DrawdownCircuitBreaker,
        uniform_weights: pd.Series,
    ) -> None:
        """TRIPPED state persists when DD stays below recovery threshold."""
        equity = _make_equity_with_dd(-0.18)
        adj, result = breaker.apply(
            uniform_weights,
            equity,
            DrawdownCircuitBreakerConfig(window_days=60),
            current_state=CircuitBreakerState.TRIPPED,
        )
        assert result.current_state == "TRIPPED"
        assert result.transitioned is False
        assert result.triggered is False
        assert result.equity_fraction == 0.20

    def test_tripped_to_recovering_above_recovery(
        self,
        breaker: DrawdownCircuitBreaker,
        uniform_weights: pd.Series,
    ) -> None:
        """TRIPPED → RECOVERING when DD rises above recovery threshold."""
        equity = _make_equity_with_dd(-0.05)  # DD = -5%, above -10% recovery
        adj, result = breaker.apply(
            uniform_weights,
            equity,
            DrawdownCircuitBreakerConfig(window_days=60),
            current_state=CircuitBreakerState.TRIPPED,
        )
        assert result.current_state == "RECOVERING"
        assert result.previous_state == "TRIPPED"
        assert result.transitioned is True
        assert result.recovery_progress_days == 1
        assert result.equity_fraction == 0.20  # still in safe mode

    def test_recovering_increments_progress(
        self,
        breaker: DrawdownCircuitBreaker,
        uniform_weights: pd.Series,
    ) -> None:
        """RECOVERING + DD above threshold → progress increments."""
        equity = _make_equity_with_dd(-0.05)
        adj, result = breaker.apply(
            uniform_weights,
            equity,
            DrawdownCircuitBreakerConfig(window_days=60),
            current_state=CircuitBreakerState.RECOVERING,
            recovery_progress_days=5,
        )
        assert result.current_state == "RECOVERING"
        assert result.transitioned is False
        assert result.recovery_progress_days == 6
        assert result.equity_fraction == 0.20  # still in safe mode

    def test_recovering_to_normal_after_confirm_days(
        self,
        breaker: DrawdownCircuitBreaker,
        uniform_weights: pd.Series,
    ) -> None:
        """RECOVERING → NORMAL when progress reaches confirm threshold."""
        equity = _make_equity_with_dd(-0.05)
        cfg = DrawdownCircuitBreakerConfig(recovery_confirm_days=21)
        adj, result = breaker.apply(
            uniform_weights,
            equity,
            cfg,
            current_state=CircuitBreakerState.RECOVERING,
            recovery_progress_days=20,
        )
        assert result.current_state == "NORMAL"
        assert result.previous_state == "RECOVERING"
        assert result.transitioned is True
        assert result.recovery_progress_days == 0
        assert result.equity_fraction == 1.0  # back to full equity

    def test_recovering_re_trips_below_recovery(
        self,
        breaker: DrawdownCircuitBreaker,
        uniform_weights: pd.Series,
    ) -> None:
        """RECOVERING → TRIPPED when DD drops back below recovery threshold."""
        equity = _make_equity_with_dd(-0.18)  # below -10% recovery but above -20%
        adj, result = breaker.apply(
            uniform_weights,
            equity,
            DrawdownCircuitBreakerConfig(window_days=60),
            current_state=CircuitBreakerState.RECOVERING,
            recovery_progress_days=3,
        )
        assert result.current_state == "TRIPPED"
        assert result.previous_state == "RECOVERING"
        assert result.transitioned is True
        assert result.triggered is True
        assert result.recovery_progress_days == 0
        assert result.equity_fraction == 0.20

    def test_recovering_still_confirming_stays_safe(
        self,
        breaker: DrawdownCircuitBreaker,
        uniform_weights: pd.Series,
    ) -> None:
        """During recovery (DD > threshold, but not yet confirmed), equity stays capped."""
        equity = _make_equity_with_dd(-0.05)
        adj, result = breaker.apply(
            uniform_weights,
            equity,
            DrawdownCircuitBreakerConfig(recovery_confirm_days=21),
            current_state=CircuitBreakerState.RECOVERING,
            recovery_progress_days=10,
        )
        assert result.current_state == "RECOVERING"
        assert result.equity_fraction == 0.20  # still in safe mode
        # Adjusted weights sum to equity_fraction
        assert float(adj.sum()) == pytest.approx(result.equity_fraction)

    def test_empty_equity_curve_preserves_state(
        self,
        breaker: DrawdownCircuitBreaker,
        uniform_weights: pd.Series,
        empty_equity: pd.Series,
    ) -> None:
        """Empty equity curve preserves current state — no DD to evaluate."""
        adj, result = breaker.apply(
            uniform_weights,
            empty_equity,
            DrawdownCircuitBreakerConfig(),
            current_state=CircuitBreakerState.TRIPPED,
        )
        assert result.current_state == "TRIPPED"
        assert result.transitioned is False
        assert result.equity_fraction == pytest.approx(1.0)
        # Weights are unchanged (pass-through)
        pd.testing.assert_series_equal(adj, uniform_weights)

    def test_short_equity_curve_still_computes_dd(
        self,
        breaker: DrawdownCircuitBreaker,
        uniform_weights: pd.Series,
        short_equity: pd.Series,
    ) -> None:
        """Short equity (< window) still produces valid DD with fewer observations."""
        adj, result = breaker.apply(
            uniform_weights,
            short_equity,
            DrawdownCircuitBreakerConfig(window_days=60),
        )
        assert result.current_state == "NORMAL"
        assert result.equity_fraction == pytest.approx(1.0)

    def test_state_machine_determinism(
        self,
        breaker: DrawdownCircuitBreaker,
        uniform_weights: pd.Series,
    ) -> None:
        """Same inputs produce identical results on repeated calls."""
        equity = _make_equity_with_dd(-0.25, window=60)
        cfg = DrawdownCircuitBreakerConfig(window_days=60)
        adj1, res1 = breaker.apply(uniform_weights, equity, cfg)
        adj2, res2 = breaker.apply(uniform_weights, equity, cfg)

        pd.testing.assert_series_equal(adj1, adj2)
        assert res1.current_state == res2.current_state
        assert res1.triggered == res2.triggered
        assert res1.equity_fraction == res2.equity_fraction
        assert res1.transitioned == res2.transitioned

    def test_weights_scaled_correctly_when_tripped(
        self,
        breaker: DrawdownCircuitBreaker,
        uniform_weights: pd.Series,
    ) -> None:
        """When tripped, each weight is scaled by safe_mode_max_equity."""
        equity = _make_equity_with_dd(-0.25, window=60)
        cfg = DrawdownCircuitBreakerConfig(safe_mode_max_equity=0.20)
        adj, result = breaker.apply(uniform_weights, equity, cfg)

        assert result.current_state == "TRIPPED"
        expected_sum = 1.0 * 0.20
        assert float(adj.sum()) == pytest.approx(expected_sum)
        for sym in uniform_weights.index:
            assert adj[sym] == pytest.approx(uniform_weights[sym] * 0.20)
