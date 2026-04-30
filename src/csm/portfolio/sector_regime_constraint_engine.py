"""Sector exposure and regime-based constraint engine.

Applies sector concentration caps via proportional scaling of over-weight
sectors and regime-based equity gating via the Phase 3.9 decision tree
(BULL / BEAR / fast-exit / fast-reentry / bear-full-cash).

Follows the standalone pattern of Phases 4.3–4.5: raw pandas in,
Pydantic config/result out.  No ``PortfolioState`` dependency.
"""

from __future__ import annotations

import logging
from typing import TypedDict

import pandas as pd
from pydantic import BaseModel, Field

from csm.risk.regime import RegimeDetector, RegimeState


class _SectorCapResult(TypedDict):
    """Internal return type for _apply_sector_cap."""

    sector_cap_applied: bool
    sectors_capped: list[str]
    sector_cap_equity_fraction: float
    n_symbols_after_cap: int
    n_holdings_min_relaxed: bool

logger: logging.Logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SectorRegimeConstraintConfig(BaseModel):
    """Configuration for the sector & regime constraint engine.

    All fields are flat (no sub-models) to keep the config surface
    aligned with the existing ``BacktestConfig`` field layout.
    """

    # -- sector cap ----------------------------------------------------------
    sector_enabled: bool = Field(default=True)
    sector_max_weight: float = Field(default=0.35, gt=0.0, le=1.0)
    n_holdings_min: int = Field(default=40, ge=1)

    # -- regime gating -------------------------------------------------------
    regime_enabled: bool = Field(default=True)
    ema_trend_window: int = Field(default=200, ge=20, le=504)
    exit_ema_window: int = Field(default=100, ge=20, le=504)
    fast_reentry_ema_window: int = Field(default=50, ge=20, le=504)
    safe_mode_max_equity: float = Field(default=0.20, gt=0.0, le=1.0)
    bear_full_cash: bool = Field(default=True)
    ema_slope_lookback_days: int = Field(default=21, ge=5, le=252)


class SectorRegimeConstraintResult(BaseModel):
    """Diagnostics from a sector & regime constraint application."""

    # -- sector cap ----------------------------------------------------------
    sector_cap_applied: bool
    sectors_capped: list[str]
    sector_cap_equity_fraction: float
    n_symbols_after_cap: int
    n_holdings_min_relaxed: bool

    # -- regime gating -------------------------------------------------------
    regime: str
    regime_equity_fraction: float

    # -- combined ------------------------------------------------------------
    final_equity_fraction: float


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class SectorRegimeConstraintEngine:
    """Apply sector exposure caps and regime-based equity gating to a weight vector.

    This is a stateless utility.  All relevant state is passed via the
    ``apply()`` method parameters.  Internally uses :class:`RegimeDetector`
    for EMA-based regime detection (direct lift from Phase 3.9 logic).
    """

    def __init__(self) -> None:
        self._detector: RegimeDetector = RegimeDetector()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply(
        self,
        weights: pd.Series,
        sector_map: dict[str, str],
        index_prices: pd.Series | None,
        asof: pd.Timestamp,
        config: SectorRegimeConstraintConfig,
        rank_scores: pd.Series | None = None,
    ) -> tuple[pd.Series, SectorRegimeConstraintResult]:
        """Apply sector caps and regime gating to *weights*.

        Args:
            weights: Target weights (post-optimizer), summing to ≈ 1.0.
            sector_map: ``{symbol: sector_code}`` mapping.
            index_prices: SET index close prices for regime detection.
                When ``None`` regime gating is skipped.
            asof: Rebalance date (used to slice *index_prices*).
            config: Constraint parameters.
            rank_scores: Optional per-symbol ranking (higher = better)
                used to decide which symbols to evict from over-cap
                sectors.  When ``None``, *weights* themselves serve as
                the ranking (higher weight = higher preference).

        Returns:
            ``(adjusted_weights, result)`` where *adjusted_weights* sum
            to *result.final_equity_fraction* (always ≤ 1.0).
        """
        # --- sector cap ---
        cap_result: _SectorCapResult
        if config.sector_enabled and not weights.empty:
            capped, cap_result = self._apply_sector_cap(
                weights, sector_map, config, rank_scores
            )
        else:
            capped = weights.copy()
            cap_result = {
                "sector_cap_applied": False,
                "sectors_capped": [],
                "sector_cap_equity_fraction": float(weights.sum()),
                "n_symbols_after_cap": len(weights),
                "n_holdings_min_relaxed": False,
            }

        # --- regime gating ---
        if config.regime_enabled and index_prices is not None:
            regime, regime_eq = self._compute_regime_equity(
                index_prices, asof, config
            )
        else:
            regime = RegimeState.BULL.value
            regime_eq = 1.0

        final_weights: pd.Series = capped * regime_eq

        return final_weights, SectorRegimeConstraintResult(
            sector_cap_applied=cap_result["sector_cap_applied"],
            sectors_capped=cap_result["sectors_capped"],
            sector_cap_equity_fraction=cap_result["sector_cap_equity_fraction"],
            n_symbols_after_cap=cap_result["n_symbols_after_cap"],
            n_holdings_min_relaxed=cap_result["n_holdings_min_relaxed"],
            regime=regime,
            regime_equity_fraction=regime_eq,
            final_equity_fraction=float(final_weights.sum()),
        )

    # ------------------------------------------------------------------
    # Sector cap
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_sector_cap(
        weights: pd.Series,
        sector_map: dict[str, str],
        config: SectorRegimeConstraintConfig,
        rank_scores: pd.Series | None = None,
    ) -> tuple[pd.Series, _SectorCapResult]:
        """Proportionally scale over-weight sectors to *sector_max_weight*.

        Excess weight from capped sectors is held as cash (not redistributed),
        so the output sum may be less than the input sum.

        When the number of symbols with non-zero weight after capping would
        drop below *n_holdings_min*, the cap is relaxed for the smallest
        over-weight sector.
        """
        max_w: float = config.sector_max_weight

        # Group symbols by sector (exclude non-positive weights).
        sector_members: dict[str, list[str]] = {}
        adjusted: dict[str, float] = {}
        for sym in weights.index:
            w: float = float(weights[sym])
            if w <= 0.0:
                adjusted[sym] = 0.0
                continue
            sector: str = sector_map.get(sym, "__unknown__")
            sector_members.setdefault(sector, []).append(sym)

        sectors_capped: list[str] = []
        total_original: float = float(weights.sum())

        for sector, members in sector_members.items():
            sector_weight: float = float(weights[members].sum())
            if sector_weight <= 0.0:
                for sym in members:
                    adjusted[sym] = 0.0
                continue

            if sector_weight <= max_w:
                for sym in members:
                    adjusted[sym] = float(weights[sym])
            else:
                sectors_capped.append(sector)
                scale: float = max_w / sector_weight
                for sym in members:
                    adjusted[sym] = float(weights[sym]) * scale

        # Build result series preserving input order.
        adjusted_series: pd.Series = pd.Series(
            [adjusted.get(sym, 0.0) for sym in weights.index],
            index=weights.index,
            dtype=float,
        )

        # n_holdings_min guard: count non-zero weights.
        n_nonzero: int = int((adjusted_series > 0.0).sum())
        n_original_nonzero: int = int((weights > 0.0).sum())
        n_holdings_min_relaxed: bool = False

        below_min: bool = n_nonzero < config.n_holdings_min
        had_enough: bool = n_original_nonzero >= config.n_holdings_min
        if below_min and had_enough and sectors_capped:
            # Relax the smallest over-weight sector.
            smallest_sector: str | None = None
            smallest_excess: float = float("inf")
            for sector in sectors_capped:
                excess: float = float(weights[sector_members[sector]].sum()) - max_w
                if 0.0 < excess < smallest_excess:
                    smallest_excess = excess
                    smallest_sector = sector

            if smallest_sector is not None:
                for sym in sector_members[smallest_sector]:
                    adjusted[sym] = float(weights[sym])
                sectors_capped.remove(smallest_sector)
                sectors_capped.sort()
                n_holdings_min_relaxed = True

                adjusted_series = pd.Series(
                    [adjusted.get(sym, 0.0) for sym in weights.index],
                    index=weights.index,
                    dtype=float,
                )

        total_after: float = float(adjusted_series.sum())
        n_after: int = int((adjusted_series > 0.0).sum())

        if sectors_capped:
            logger.info(
                "Sector cap: %d sector(s) capped (%s); sum %.4f → %.4f",
                len(sectors_capped),
                ", ".join(sectors_capped),
                total_original,
                total_after,
            )

        return adjusted_series, {
            "sector_cap_applied": bool(sectors_capped),
            "sectors_capped": sectors_capped,
            "sector_cap_equity_fraction": total_after,
            "n_symbols_after_cap": n_after,
            "n_holdings_min_relaxed": n_holdings_min_relaxed,
        }

    # ------------------------------------------------------------------
    # Regime gating (direct lift from Phase 3.9 backtest.py)
    # ------------------------------------------------------------------

    def _compute_regime_equity(
        self,
        index_prices: pd.Series,
        asof: pd.Timestamp,
        config: SectorRegimeConstraintConfig,
    ) -> tuple[str, float]:
        """Compute equity fraction from regime detection.

        Decision tree (identical to Phase 3.9):

        =======  =============================  ======================
        Regime   Condition                      equity_fraction
        =======  =============================  ======================
        BULL     SET < EMA100 (fast exit)       safe_mode_max_equity
        BULL     Otherwise                      1.0
        BEAR     SET > EMA50 (fast reentry)     1.0
        BEAR     EMA200 slope negative + full    0.0
        BEAR     Otherwise (weak bear)           safe_mode_max_equity
        =======  =============================  ======================
        """
        is_bull: bool = self._detector.is_bull_market(
            index_prices, asof, window=config.ema_trend_window
        )
        regime: str

        if is_bull:
            regime = RegimeState.BULL.value
            is_fast_exit: bool = not self._detector.is_bull_market(
                index_prices, asof, window=config.exit_ema_window
            )
            equity = config.safe_mode_max_equity if is_fast_exit else 1.0
        else:
            regime = RegimeState.BEAR.value
            is_fast_reentry: bool = self._detector.is_bull_market(
                index_prices, asof, window=config.fast_reentry_ema_window
            )
            if is_fast_reentry:
                equity = 1.0
            elif config.bear_full_cash and self._detector.has_negative_ema_slope(
                index_prices,
                asof,
                window=config.ema_trend_window,
                slope_lookback=config.ema_slope_lookback_days,
            ):
                equity = 0.0
            else:
                equity = config.safe_mode_max_equity

        logger.debug("Regime: %s → equity_fraction=%.2f", regime, equity)
        return regime, equity


__all__: list[str] = [
    "SectorRegimeConstraintConfig",
    "SectorRegimeConstraintEngine",
    "SectorRegimeConstraintResult",
]
