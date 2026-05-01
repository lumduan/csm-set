"""Per-position liquidity and capacity overlay.

Caps each target position's notional at a configurable fraction of its
63-day average daily turnover (ADTV), reducing oversized positions and
holding the excess as cash.  Also provides a strategy capacity curve
helper for AUM sensitivity analysis.
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

logger: logging.Logger = logging.getLogger(__name__)


class PositionLiquidityInfo(BaseModel):
    """Per-symbol liquidity diagnostics."""

    symbol: str
    adtv_thb: float
    target_notional: float
    capped_notional: float
    original_weight: float
    adjusted_weight: float
    participation_rate: float
    cap_binding: bool


class LiquidityConfig(BaseModel):
    """Configuration for the liquidity and capacity overlay."""

    enabled: bool = Field(default=True)
    adv_cap_pct: float = Field(default=0.10, gt=0.0, le=1.0)
    adtv_lookback_days: int = Field(default=63, ge=21, le=504)
    assumed_aum_thb: float = Field(default=200_000_000, gt=0.0)


class LiquidityResult(BaseModel):
    """Result of a liquidity overlay application."""

    effective_equity_fraction: float
    n_capped: int
    n_total: int
    n_zero_adtv: int
    per_position: dict[str, PositionLiquidityInfo]
    total_target_notional: float
    total_capped_notional: float


class LiquidityOverlay:
    """Cap per-position notionals at a fraction of trailing ADTV.

    This is a stateless utility.  All relevant state is passed via the
    ``apply()`` method parameters.
    """

    def apply(
        self,
        weights: pd.Series,
        prices: pd.DataFrame,
        volumes: pd.DataFrame,
        config: LiquidityConfig,
    ) -> tuple[pd.Series, LiquidityResult]:
        """Cap position sizes so no single position exceeds its ADTV cap.

        Args:
            weights: Raw target weights (post-optimizer / post-scaler),
                     summing to ≤ 1.0.
            prices: Wide-form close-price DataFrame indexed by date.
            volumes: Wide-form volume DataFrame indexed by date.
            config: LiquidityConfig with cap and AUM settings.

        Returns:
            ``(adjusted_weights, result)`` where *adjusted_weights* sum to
            *result.effective_equity_fraction* (always ≤ 1.0).
        """
        if not config.enabled:
            return weights.copy(), LiquidityResult(
                effective_equity_fraction=float(weights.sum()),
                n_capped=0,
                n_total=len(weights),
                n_zero_adtv=0,
                per_position={},
                total_target_notional=config.assumed_aum_thb * float(weights.sum()),
                total_capped_notional=config.assumed_aum_thb * float(weights.sum()),
            )

        if weights.empty:
            return pd.Series(dtype=float), LiquidityResult(
                effective_equity_fraction=0.0,
                n_capped=0,
                n_total=0,
                n_zero_adtv=0,
                per_position={},
                total_target_notional=0.0,
                total_capped_notional=0.0,
            )

        adtv: pd.Series = self._compute_adtv(prices, volumes, config.adtv_lookback_days)

        adjusted_weights: list[float] = []
        per_position: dict[str, PositionLiquidityInfo] = {}
        n_capped: int = 0
        n_zero_adtv: int = 0
        total_target: float = 0.0
        total_capped: float = 0.0
        aum: float = config.assumed_aum_thb
        cap: float = config.adv_cap_pct

        for sym in weights.index:
            w: float = float(weights[sym])
            if w <= 0.0:
                adjusted_weights.append(0.0)
                continue

            sym_adtv: float = float(adtv.get(sym, 0.0))
            target_notional: float = w * aum
            total_target += target_notional

            if sym_adtv <= 0.0 or math.isnan(sym_adtv):
                n_zero_adtv += 1
                adjusted_weights.append(0.0)
                logger.warning("Liquidity overlay: zero/NaN ADTV for %s — weight zeroed", sym)
                per_position[sym] = PositionLiquidityInfo(
                    symbol=sym,
                    adtv_thb=0.0,
                    target_notional=target_notional,
                    capped_notional=0.0,
                    original_weight=w,
                    adjusted_weight=0.0,
                    participation_rate=float("inf"),
                    cap_binding=True,
                )
                continue

            participation: float = target_notional / sym_adtv

            if participation > cap:
                capped_notional: float = cap * sym_adtv
                adj_w: float = capped_notional / aum
                n_capped += 1
                cap_binding: bool = True
            else:
                capped_notional = target_notional
                adj_w = w
                cap_binding = False

            total_capped += capped_notional
            adjusted_weights.append(adj_w)

            per_position[sym] = PositionLiquidityInfo(
                symbol=sym,
                adtv_thb=sym_adtv,
                target_notional=target_notional,
                capped_notional=capped_notional,
                original_weight=w,
                adjusted_weight=adj_w,
                participation_rate=participation,
                cap_binding=cap_binding,
            )

        adjusted: pd.Series = pd.Series(
            adjusted_weights,
            index=weights.index,
            dtype=float,
        )
        equity_fraction: float = float(adjusted.sum())

        if n_capped:
            logger.info(
                "Liquidity overlay: capped %d/%d positions; equity fraction %.4f → %.4f",
                n_capped,
                len(weights),
                float(weights.sum()),
                equity_fraction,
            )

        return adjusted, LiquidityResult(
            effective_equity_fraction=equity_fraction,
            n_capped=n_capped,
            n_total=len(weights),
            n_zero_adtv=n_zero_adtv,
            per_position=per_position,
            total_target_notional=total_target,
            total_capped_notional=total_capped,
        )

    @staticmethod
    def _compute_adtv(
        prices: pd.DataFrame,
        volumes: pd.DataFrame,
        lookback_days: int,
    ) -> pd.Series:
        """Compute 63-day average daily turnover (ADTV) per symbol.

        ADTV = mean(close × volume) over the trailing *lookback_days*
        calendar bars.  Symbols absent from either frame are excluded.
        """
        adtv_values: dict[str, float] = {}
        common_symbols: set[str] = set(prices.columns) & set(volumes.columns)

        for sym in common_symbols:
            close_hist: pd.Series = prices[sym].dropna().tail(lookback_days)
            vol_hist: pd.Series = volumes[sym].dropna().tail(lookback_days)
            min_len: int = min(len(close_hist), len(vol_hist))
            if min_len == 0:
                continue
            turnover: pd.Series = close_hist.iloc[-min_len:] * vol_hist.iloc[-min_len:]
            adtv_values[sym] = float(turnover.mean())

        return pd.Series(adtv_values, dtype=float)


def compute_capacity_curve(
    weights: pd.Series,
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    config: LiquidityConfig | None = None,
    aum_grid: list[float] | None = None,
) -> pd.DataFrame:
    """Compute strategy capacity curve over a grid of AUM levels.

    At each AUM level, applies the liquidity overlay and reports the
    fraction of positions capped, effective equity fraction, and maximum
    participation rate.

    Args:
        weights: Raw target weights summing to ≤ 1.0.
        prices: Wide-form close-price DataFrame indexed by date.
        volumes: Wide-form volume DataFrame indexed by date.
        config: Base LiquidityConfig (defaults to LiquidityConfig()).
        aum_grid: List of AUM values in THB.  Defaults to a log-spaced
            grid from 10M to 10B with 20 points.

    Returns:
        DataFrame with columns: ``aum_thb, n_capped, fraction_capped,
        effective_equity_fraction, max_participation_rate``.
    """
    if config is None:
        config = LiquidityConfig()

    if aum_grid is None:
        aum_grid = list(
            np.logspace(
                math.log10(10_000_000),
                math.log10(10_000_000_000),
                num=20,
            )
        )

    overlay = LiquidityOverlay()
    rows: list[dict[str, float]] = []

    for aum in aum_grid:
        cfg: LiquidityConfig = LiquidityConfig(
            enabled=config.enabled,
            adv_cap_pct=config.adv_cap_pct,
            adtv_lookback_days=config.adtv_lookback_days,
            assumed_aum_thb=aum,
        )
        _adj, result = overlay.apply(weights, prices, volumes, cfg)

        max_pr: float = 0.0
        for info in result.per_position.values():
            if not math.isinf(info.participation_rate):
                max_pr = max(max_pr, info.participation_rate)

        rows.append(
            {
                "aum_thb": aum,
                "n_capped": float(result.n_capped),
                "fraction_capped": (result.n_capped / result.n_total if result.n_total else 0.0),
                "effective_equity_fraction": result.effective_equity_fraction,
                "max_participation_rate": max_pr,
            }
        )

    return pd.DataFrame(rows)


__all__: list[str] = [
    "LiquidityConfig",
    "LiquidityOverlay",
    "LiquidityResult",
    "PositionLiquidityInfo",
    "compute_capacity_curve",
]
