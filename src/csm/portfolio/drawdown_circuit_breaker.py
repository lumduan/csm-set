"""Drawdown circuit breaker overlay.

Monitors rolling portfolio drawdown and disables or scales down risk when
a configurable threshold is breached.  Uses a state machine with hysteresis
so the strategy can recover naturally as the drawdown window rolls past
the trough.
"""

from __future__ import annotations

import logging
import math
from typing import Self

import pandas as pd
from pydantic import BaseModel, Field, model_validator

from csm.portfolio.state import CircuitBreakerState
from csm.risk.drawdown import DrawdownAnalyzer

logger: logging.Logger = logging.getLogger(__name__)


class DrawdownCircuitBreakerConfig(BaseModel):
    """Configuration for the drawdown circuit breaker overlay.

    Uses a dual-threshold hysteresis design:

    - **trigger_threshold** (-0.10): DD must breach this to trip the breaker.
    - **recovery_threshold** (-0.05): DD must improve past this to begin recovery.
    - **recovery_buffer**: the intentional gap between trip and recovery
      thresholds, preventing oscillation (whipsaw) during volatile markets.
    """

    enabled: bool = Field(default=True)
    window_days: int = Field(default=60, ge=1, le=504)
    trigger_threshold: float = Field(default=-0.10, ge=-1.0, le=0.0)
    recovery_threshold: float = Field(default=-0.05, ge=-1.0, le=0.0)
    recovery_buffer: float = Field(default=0.05, ge=0.0, le=1.0)
    recovery_confirm_days: int = Field(default=21, ge=1, le=252)
    safe_mode_max_equity: float = Field(default=0.20, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_thresholds(self) -> Self:
        """recovery_threshold must be greater than trigger_threshold."""
        if self.recovery_threshold <= self.trigger_threshold:
            raise ValueError(
                f"recovery_threshold ({self.recovery_threshold}) must be "
                f"greater than trigger_threshold ({self.trigger_threshold})"
            )
        expected_gap = self.recovery_threshold - self.trigger_threshold
        if abs(expected_gap - self.recovery_buffer) > 1e-9:
            raise ValueError(
                f"recovery_buffer ({self.recovery_buffer}) must equal "
                f"recovery_threshold - trigger_threshold ({expected_gap:.4f})"
            )
        return self


class CircuitBreakerResult(BaseModel):
    """Result of a drawdown circuit breaker application."""

    triggered: bool
    current_state: str
    rolling_drawdown: float
    equity_fraction: float
    recovery_progress_days: int
    previous_state: str
    transitioned: bool


class DrawdownCircuitBreaker:
    """Stateful drawdown circuit breaker overlay.

    Tracks a state machine (NORMAL → TRIPPED → RECOVERING → NORMAL)
    keyed off rolling N-day drawdown.  The caller is responsible for
    threading *current_state* and *recovery_progress_days* through
    successive rebalance periods.

    In backtest mode the breaker applies safe-mode equity but never
    raises.  The :class:`CircuitBreakerTripped` exception is reserved for
    Phase 5 live-trading wiring.
    """

    def apply(
        self,
        weights: pd.Series,
        equity_curve: pd.Series,
        config: DrawdownCircuitBreakerConfig,
        current_state: CircuitBreakerState = CircuitBreakerState.NORMAL,
        recovery_progress_days: int = 0,
    ) -> tuple[pd.Series, CircuitBreakerResult]:
        """Apply the circuit breaker to *weights* based on rolling drawdown.

        Args:
            weights: Target weights (post-optimizer / post-scaler),
                     summing to ≤ 1.0.
            equity_curve: Portfolio equity curve indexed by date, up to the
                          current rebalance date.
            config: :class:`DrawdownCircuitBreakerConfig` with thresholds.
            current_state: The breaker state from the previous rebalance.
            recovery_progress_days: Consecutive days above recovery threshold
                                   from the previous rebalance.

        Returns:
            ``(adjusted_weights, result)`` where *adjusted_weights* are
            scaled by the computed equity fraction.
        """
        if not config.enabled:
            return weights.copy(), CircuitBreakerResult(
                triggered=False,
                current_state=CircuitBreakerState.NORMAL.value,
                rolling_drawdown=0.0,
                equity_fraction=float(weights.sum()) if not weights.empty else 1.0,
                recovery_progress_days=0,
                previous_state=CircuitBreakerState.NORMAL.value,
                transitioned=False,
            )

        if weights.empty:
            return pd.Series(dtype=float), CircuitBreakerResult(
                triggered=False,
                current_state=current_state.value,
                rolling_drawdown=0.0,
                equity_fraction=0.0,
                recovery_progress_days=recovery_progress_days,
                previous_state=current_state.value,
                transitioned=False,
            )

        if equity_curve.empty:
            # Cannot compute DD — preserve current state, no scaling
            logger.warning(
                "Circuit breaker: empty equity curve — preserving state %s",
                current_state.value,
            )
            return weights.copy(), CircuitBreakerResult(
                triggered=False,
                current_state=current_state.value,
                rolling_drawdown=0.0,
                equity_fraction=1.0,
                recovery_progress_days=recovery_progress_days,
                previous_state=current_state.value,
                transitioned=False,
            )

        analyzer = DrawdownAnalyzer()
        rolling_dd: pd.Series = analyzer.rolling_drawdown(
            equity_curve, config.window_days
        )
        latest_dd: float = 0.0
        if not rolling_dd.empty:
            val: float = float(rolling_dd.iloc[-1])
            latest_dd = val if not math.isnan(val) else 0.0

        triggered: bool = False
        new_state: CircuitBreakerState = current_state
        new_progress: int = recovery_progress_days
        equity_fraction: float = 1.0
        transitioned: bool = False

        if current_state == CircuitBreakerState.NORMAL:
            if latest_dd <= config.trigger_threshold:
                triggered = True
                new_state = CircuitBreakerState.TRIPPED
                equity_fraction = config.safe_mode_max_equity
                transitioned = True
                logger.warning(
                    "Circuit breaker TRIPPED: rolling DD %.4f ≤ trigger %.4f",
                    latest_dd,
                    config.trigger_threshold,
                )
            else:
                equity_fraction = 1.0

        elif current_state == CircuitBreakerState.TRIPPED:
            if latest_dd > config.recovery_threshold:
                new_state = CircuitBreakerState.RECOVERING
                new_progress = 1
                equity_fraction = config.safe_mode_max_equity
                transitioned = True
                logger.info(
                    "Circuit breaker RECOVERING: rolling DD %.4f > recovery %.4f",
                    latest_dd,
                    config.recovery_threshold,
                )
            else:
                equity_fraction = config.safe_mode_max_equity

        elif current_state == CircuitBreakerState.RECOVERING:
            if latest_dd > config.recovery_threshold:
                new_progress = recovery_progress_days + 1
                if new_progress >= config.recovery_confirm_days:
                    new_state = CircuitBreakerState.NORMAL
                    new_progress = 0
                    equity_fraction = 1.0
                    transitioned = True
                    logger.info(
                        "Circuit breaker NORMAL: recovery confirmed after %d days",
                        recovery_progress_days + 1,
                    )
                else:
                    equity_fraction = config.safe_mode_max_equity
            else:
                triggered = True
                new_state = CircuitBreakerState.TRIPPED
                new_progress = 0
                equity_fraction = config.safe_mode_max_equity
                transitioned = True
                logger.warning(
                    "Circuit breaker RE-TRIPPED: rolling DD %.4f ≤ recovery %.4f",
                    latest_dd,
                    config.recovery_threshold,
                )

        scaled: pd.Series = weights * equity_fraction

        return scaled, CircuitBreakerResult(
            triggered=triggered,
            current_state=new_state.value,
            rolling_drawdown=latest_dd,
            equity_fraction=equity_fraction,
            recovery_progress_days=new_progress,
            previous_state=current_state.value,
            transitioned=transitioned,
        )


__all__: list[str] = [
    "CircuitBreakerResult",
    "DrawdownCircuitBreaker",
    "DrawdownCircuitBreakerConfig",
]
