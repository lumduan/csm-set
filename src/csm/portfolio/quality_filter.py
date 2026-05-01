"""Quality-first universe filter.

Drops stocks that fail fundamental quality criteria (positive earnings,
minimum net profit margin) before momentum ranking.  In backtest /
synthetic-data environments where fundamental data is unavailable, a
trailing-return quality proxy is used instead.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

logger: logging.Logger = logging.getLogger(__name__)


class QualityFilterConfig(BaseModel):
    """Configuration for the quality-first universe filter."""

    enabled: bool = Field(default=True)
    require_positive_earnings: bool = Field(default=True)
    min_net_profit_margin: float = Field(default=0.0, ge=-1.0, le=1.0)
    lookback_quarters: int = Field(default=4, ge=1, le=20)
    synthetic_quality_threshold: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Minimum trailing 126d return when using synthetic proxy",
    )


class QualityFilterResult(BaseModel):
    """Result of a quality filter application."""

    n_before: int
    n_after: int
    n_filtered: int
    filtered_reasons: dict[str, list[str]]


class QualityFilter:
    """Filter a cross-section based on fundamental / quality criteria.

    When *fundamental_data* is provided (production path), symbols are
    screened on earnings positivity and net profit margin.  When only
    *price_data* is available (synthetic / backtest path), a trailing
    126-day return > *synthetic_quality_threshold* proxy is used.
    """

    def apply(
        self,
        symbols: list[str],
        config: QualityFilterConfig,
        *,
        fundamental_data: dict[str, dict[str, float]] | None = None,
        price_data: pd.DataFrame | None = None,
    ) -> tuple[list[str], QualityFilterResult]:
        """Filter *symbols*, returning those that satisfy quality criteria.

        Args:
            symbols: Candidate symbols to screen.
            config: :class:`QualityFilterConfig`.
            fundamental_data: Optional ``symbol -> {metric: value}`` mapping.
            price_data: Optional wide-form close-price DataFrame (used when
                *fundamental_data* is ``None``).

        Returns:
            ``(filtered_symbols, result)``.
        """
        n_before: int = len(symbols)

        if not config.enabled:
            return list(symbols), QualityFilterResult(
                n_before=n_before,
                n_after=n_before,
                n_filtered=0,
                filtered_reasons={},
            )

        if fundamental_data is not None:
            return self._apply_fundamental(symbols, config, fundamental_data)

        if price_data is not None:
            return self._apply_synthetic_proxy(symbols, config, price_data)

        logger.warning("QualityFilter: no fundamental or price data — pass-through")
        return list(symbols), QualityFilterResult(
            n_before=n_before,
            n_after=n_before,
            n_filtered=0,
            filtered_reasons={},
        )

    # ── fundamental path ──────────────────────────────────────────────

    @staticmethod
    def _apply_fundamental(
        symbols: list[str],
        config: QualityFilterConfig,
        fundamental_data: dict[str, dict[str, float]],
    ) -> tuple[list[str], QualityFilterResult]:
        reasons: dict[str, list[str]] = {}

        passed: list[str] = []
        for sym in symbols:
            fd = fundamental_data.get(sym)
            if fd is None:
                reasons.setdefault("no_fundamental_data", []).append(sym)
                continue

            if config.require_positive_earnings and fd.get("earnings", 0.0) <= 0:
                reasons.setdefault("negative_earnings", []).append(sym)
                continue

            npm = fd.get("net_profit_margin", 0.0)
            if npm < config.min_net_profit_margin:
                reasons.setdefault("low_profit_margin", []).append(sym)
                continue

            passed.append(sym)

        return passed, QualityFilterResult(
            n_before=len(symbols),
            n_after=len(passed),
            n_filtered=len(symbols) - len(passed),
            filtered_reasons=reasons,
        )

    # ── synthetic proxy path ─────────────────────────────────────────

    @staticmethod
    def _apply_synthetic_proxy(
        symbols: list[str],
        config: QualityFilterConfig,
        price_data: pd.DataFrame,
    ) -> tuple[list[str], QualityFilterResult]:
        # Trailing 126-day return as quality proxy
        available = [s for s in symbols if s in price_data.columns]
        if not available or len(price_data) < 126:
            return list(symbols), QualityFilterResult(
                n_before=len(symbols),
                n_after=len(symbols),
                n_filtered=0,
                filtered_reasons={},
            )

        tail = price_data[available].iloc[-126:]
        trailing_ret = tail.iloc[-1] / tail.iloc[0] - 1.0

        failed: list[str] = []
        passed: list[str] = []
        for sym in available:
            if sym in trailing_ret.index and not np.isnan(trailing_ret[sym]):
                if trailing_ret[sym] > config.synthetic_quality_threshold:
                    passed.append(sym)
                else:
                    failed.append(sym)
            else:
                passed.append(sym)  # insufficient data → keep

        reasons: dict[str, list[str]] = {}
        if failed:
            reasons["negative_trailing_return"] = failed

        return passed, QualityFilterResult(
            n_before=len(symbols),
            n_after=len(passed),
            n_filtered=len(symbols) - len(passed),
            filtered_reasons=reasons,
        )


__all__: list[str] = [
    "QualityFilter",
    "QualityFilterConfig",
    "QualityFilterResult",
]
