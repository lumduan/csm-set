"""Portfolio selection and construction utilities."""

from __future__ import annotations

import logging

import pandas as pd
from pydantic import BaseModel, Field

from csm.config.constants import (
    BUFFER_RANK_THRESHOLD,
    BULL_MODE_N_HOLDINGS_MAX,
    BULL_MODE_N_HOLDINGS_MIN,
    EXIT_RANK_FLOOR,
)
from csm.portfolio.exceptions import PortfolioError

logger: logging.Logger = logging.getLogger(__name__)


class SelectionConfig(BaseModel):
    """Configuration for the portfolio selection step."""

    n_holdings_min: int = Field(default=BULL_MODE_N_HOLDINGS_MIN, ge=1, le=200)
    n_holdings_max: int = Field(default=BULL_MODE_N_HOLDINGS_MAX, ge=1, le=200)
    buffer_rank_threshold: float = Field(default=BUFFER_RANK_THRESHOLD, ge=0.0, le=1.0)
    exit_rank_floor: float = Field(default=EXIT_RANK_FLOOR, ge=0.0, le=1.0)


class SelectionResult(BaseModel):
    """Output of PortfolioConstructor.select()."""

    selected: list[str] = Field(default_factory=list)
    evicted: list[str] = Field(default_factory=list)
    retained: list[str] = Field(default_factory=list)
    ranks: dict[str, float] = Field(default_factory=dict)


class PortfolioConstructor:
    """Build portfolio holdings from ranked signals and target weights.

    Phase 4.1 promotes the Phase 3.9 inline selection logic into a standalone,
    testable API.  ``select()`` implements top-quintile composite z-score
    selection with a replacement buffer, unconditional exit-rank floor, and
    optional entry-mask gate.
    """

    def select(
        self,
        cross_section: pd.DataFrame,
        current_holdings: list[str],
        config: SelectionConfig,
        *,
        entry_mask: set[str] | None = None,
    ) -> SelectionResult:
        """Select 40–60 holdings using composite z-score + buffer logic.

        When *entry_mask* is provided, candidates for new entry are restricted
        to symbols in the mask, but existing holdings are always eligible for
        buffer retention (``"entry_only"`` RS filter gate).

        Falls back to the single top-ranked candidate when the eligible pool
        cannot fill *n_holdings_min*, ensuring at least one symbol is always
        returned.
        """
        if cross_section.empty:
            return SelectionResult()

        composite: pd.Series = cross_section.mean(axis=1)

        # Restrict candidate pool to entry_mask when provided (entry-only RS gate).
        if entry_mask is not None and entry_mask:
            eligible_composite: pd.Series = composite[composite.index.isin(entry_mask)]
            if eligible_composite.empty:
                eligible_composite = composite  # fallback if gate emptied the pool
        else:
            eligible_composite = composite

        # Take top n_holdings_max candidates by raw composite score.
        n_max: int = min(config.n_holdings_max, len(eligible_composite))
        candidates: list[str] = [str(s) for s in eligible_composite.nlargest(n_max).index]

        # Apply buffer to reduce unnecessary churn (also applies exit-rank floor).
        buffered, evicted, retained = self._apply_buffer_logic(
            current_holdings,
            candidates,
            cross_section,
            config.buffer_rank_threshold,
            config.exit_rank_floor,
        )

        # Enforce bounds: cap at n_holdings_max, ensure at least n_holdings_min.
        buffered = buffered[: config.n_holdings_max]
        if len(buffered) < config.n_holdings_min and len(candidates) >= config.n_holdings_min:
            extra: list[str] = [c for c in candidates if c not in set(buffered)]
            buffered.extend(extra[: config.n_holdings_min - len(buffered)])

        if not buffered:
            buffered = candidates[:1]

        # Build percentile-rank map for the full cross-section.
        pct_rank: pd.Series = composite.rank(pct=True)
        ranks: dict[str, float] = {str(idx): float(pct_rank[idx]) for idx in cross_section.index}

        return SelectionResult(
            selected=buffered,
            evicted=evicted,
            retained=retained,
            ranks=ranks,
        )

    @staticmethod
    def _apply_buffer_logic(
        current_holdings: list[str],
        candidates: list[str],
        cross_section: pd.DataFrame,
        buffer_threshold: float,
        exit_rank_floor: float,
    ) -> tuple[list[str], list[str], list[str]]:
        """Apply buffer-and-eviction logic.

        Uses cross-sectional percentile rank (0–1) of the composite z-score so
        comparisons are scale-invariant across rebalance dates.

        Phase 3.9: holdings ranked below *exit_rank_floor* are evicted
        unconditionally regardless of whether any replacement qualifies — they
        have fallen to the bottom of the universe and buffer protection no
        longer applies.

        Returns:
            (final_list, evicted_symbols, retained_symbols)
        """
        if not current_holdings:
            return candidates, [], []

        composite: pd.Series = cross_section.mean(axis=1)
        pct_rank: pd.Series = composite.rank(pct=True)

        candidate_set: set[str] = set(candidates)
        final: list[str] = []
        evicted: list[str] = []
        retained_syms: list[str] = []

        for sym in current_holdings:
            if sym in candidate_set:
                final.append(sym)
                candidate_set.discard(sym)
                retained_syms.append(sym)
            else:
                current_rank: float = float(pct_rank.get(sym, 0.0))
                if exit_rank_floor > 0.0 and current_rank < exit_rank_floor:
                    evicted.append(sym)
                    continue  # unconditional eviction — below the exit floor
                best_replacement_rank: float = max(
                    (float(pct_rank.get(c, 0.0)) for c in candidate_set), default=0.0
                )
                if best_replacement_rank - current_rank >= buffer_threshold:
                    evicted.append(sym)  # replaced by top candidates below
                else:
                    final.append(sym)
                    retained_syms.append(sym)

        # Fill remaining slots with highest-ranked new candidates not yet included.
        final_set: set[str] = set(final)
        new_entries: list[str] = [c for c in candidates if c not in final_set]
        final.extend(new_entries)

        return final, evicted, retained_syms

    def build(self, selected: list[str], weights: pd.Series, as_of: pd.Timestamp) -> pd.DataFrame:
        """Build a holdings DataFrame from selected names and weights.

        Args:
            selected: Selected symbol list.
            weights: Weight vector indexed by symbol.
            as_of: Rebalance date.

        Returns:
            Holdings DataFrame with symbol, weight, and as_of columns.

        Raises:
            PortfolioError: If weights are invalid.
        """

        if (weights < 0.0).any():
            raise PortfolioError("Portfolio weights must be non-negative.")
        total_weight: float = float(weights.sum())
        if abs(total_weight - 1.0) > 1e-6:
            raise PortfolioError("Portfolio weights must sum to 1.0.")
        holdings: pd.DataFrame = pd.DataFrame(
            {
                "symbol": selected,
                "weight": weights.reindex(selected).fillna(0.0).to_numpy(),
                "as_of": as_of,
            }
        )
        return holdings


__all__: list[str] = ["PortfolioConstructor", "SelectionConfig", "SelectionResult"]
