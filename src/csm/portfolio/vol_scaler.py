"""Portfolio-level volatility scaling engine.

Computes trailing realized volatility from position weights and price history,
then scales the weight vector so total equity exposure targets a specified
annualized volatility.
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

logger: logging.Logger = logging.getLogger(__name__)


class VolScalingConfig(BaseModel):
    """Configuration for the volatility scaling engine."""

    enabled: bool = Field(default=True)
    target_annual: float = Field(default=0.15, gt=0.0, le=1.0)
    lookback_days: int = Field(default=63, ge=21, le=504)
    cap: float = Field(default=1.5, ge=1.0, le=3.0)
    floor: float = Field(default=0.0, ge=0.0, le=1.0)
    regime_aware: bool = Field(default=False)
    fast_lookback_days: int = Field(default=21, ge=10, le=126)
    fast_blend_weight: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Weight on fast-window vol; 0 = slow only, 0.5 = equal blend",
    )


class VolScalingResult(BaseModel):
    """Result of a volatility scaling computation."""

    realized_vol_annual: float
    scale_factor: float
    equity_fraction: float
    slow_realized_vol: float = 0.0
    fast_realized_vol: float = 0.0
    blended: bool = False


class VolatilityScaler:
    """Scale portfolio weights to target a specified annualized volatility.

    This is a stateless utility.  All relevant state is passed via the
    ``scale()`` method parameters.
    """

    def scale(
        self,
        weights: pd.Series,
        prices: pd.DataFrame,
        config: VolScalingConfig,
    ) -> tuple[pd.Series, VolScalingResult]:
        """Scale *weights* so portfolio vol approximates ``config.target_annual``.

        Args:
            weights: Raw target weights (post-optimizer), summing to 1.0.
            prices: Wide-form close-price DataFrame indexed by date.
            config: VolScalingConfig with scaling parameters.

        Returns:
            ``(scaled_weights, result)`` where *scaled_weights* sums to
            *result.equity_fraction* (always ≤ 1.0).
        """
        if not config.enabled:
            return weights.copy(), VolScalingResult(
                realized_vol_annual=0.0,
                scale_factor=1.0,
                equity_fraction=1.0,
            )

        if weights.empty:
            return pd.Series(dtype=float), VolScalingResult(
                realized_vol_annual=0.0,
                scale_factor=config.cap,
                equity_fraction=config.cap,
            )

        if config.fast_blend_weight > 0.0:
            realized, slow_vol, fast_vol = self._compute_blended_vol(
                weights, prices, config.lookback_days,
                config.fast_lookback_days, config.fast_blend_weight,
            )
            blended = True
        else:
            realized = self._compute_realized_vol(
                weights, prices, config.lookback_days,
            )
            slow_vol = realized
            fast_vol = 0.0
            blended = False

        if math.isnan(realized) or realized <= 0.0:
            scale_factor: float = config.cap
        else:
            raw: float = config.target_annual / realized
            scale_factor = float(np.clip(raw, config.floor, config.cap))

        equity_fraction: float = min(scale_factor, 1.0)
        scaled: pd.Series = weights * equity_fraction

        logger.info(
            "Vol scaling: realized=%.4f target=%.4f scale=%.4f equity=%.4f",
            realized,
            config.target_annual,
            scale_factor,
            equity_fraction,
        )

        return scaled, VolScalingResult(
            realized_vol_annual=realized if not math.isnan(realized) else 0.0,
            scale_factor=scale_factor,
            equity_fraction=equity_fraction,
            slow_realized_vol=slow_vol if not math.isnan(slow_vol) else 0.0,
            fast_realized_vol=fast_vol if not math.isnan(fast_vol) else 0.0,
            blended=blended,
        )

    @staticmethod
    def _compute_realized_vol(
        weights: pd.Series,
        prices: pd.DataFrame,
        lookback_days: int,
    ) -> float:
        """Compute annualized realized portfolio volatility.

        Steps:
            1. Align weights to symbols present in *prices*.
            2. Renormalize aligned weights to sum to 1.0.
            3. Compute trailing daily returns, tailed to *lookback_days*.
            4. Require at least 21 observations.
            5. Portfolio daily returns = dot product with aligned weights.
            6. Annualize: std × sqrt(252).

        Returns:
            Annualized volatility as a float, or ``NaN`` when data is insufficient.
        """
        available: list[str] = [s for s in weights.index if s in prices.columns]
        if not available:
            return float("nan")

        w: pd.Series = weights[available].copy()
        w_sum: float = float(w.sum())
        if w_sum <= 0.0:
            return float("nan")
        w = w / w_sum

        returns: pd.DataFrame = (
            prices[available].pct_change().dropna(how="all").tail(lookback_days)
        )
        if len(returns) < 21:
            return float("nan")

        port_daily: np.ndarray = returns.to_numpy().dot(w.to_numpy())
        return float(np.std(port_daily) * math.sqrt(252))

    @staticmethod
    def _compute_blended_vol(
        weights: pd.Series,
        prices: pd.DataFrame,
        slow_lookback: int,
        fast_lookback: int,
        fast_weight: float,
    ) -> tuple[float, float, float]:
        """Compute blended realized vol from slow and fast windows.

        Returns:
            ``(blended, slow, fast)`` where *blended* is the weighted
            blend of the two estimates.  Falls back to slow-only when
            the fast window has insufficient data.
        """
        slow: float = VolatilityScaler._compute_realized_vol(
            weights, prices, slow_lookback,
        )
        fast: float = VolatilityScaler._compute_realized_vol(
            weights, prices, fast_lookback,
        )

        if math.isnan(fast) or fast <= 0.0:
            return slow, slow, 0.0

        if math.isnan(slow) or slow <= 0.0:
            return fast, 0.0, fast

        blended: float = (1.0 - fast_weight) * slow + fast_weight * fast
        return blended, slow, fast


__all__: list[str] = [
    "VolScalingConfig",
    "VolScalingResult",
    "VolatilityScaler",
]
