"""Sector-relative feature computations for csm-set."""

import logging

import numpy as np
import pandas as pd

logger: logging.Logger = logging.getLogger(__name__)

# 253 prices required: gives valid iloc[-22] (t-21) and iloc[-253] (t-252),
# the two boundary prices for mom_12_1 — consistent with Phase 2.1 start_td=252.
_MIN_HIST: int = 253

_SIGNAL_NAMES: list[str] = ["sector_rel_strength"]


def _mom_12_1(hist: pd.Series) -> float:
    """log(hist.iloc[-22] / hist.iloc[-253]). Returns NaN if any boundary price <= 0 or NaN."""
    end_p = float(hist.iloc[-22])
    start_p = float(hist.iloc[-253])
    if pd.isna(end_p) or pd.isna(start_p) or end_p <= 0.0 or start_p <= 0.0:
        return float("nan")
    return float(np.log(end_p / start_p))


class SectorFeatures:
    """Compute sector-relative momentum features."""

    def compute(
        self,
        symbol_close: pd.Series,
        sector_closes: dict[str, pd.Series],
        symbol_sector: str,
        rebalance_dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """Compute sector_rel_strength per rebalance date.

        sector_rel_strength = mom_12_1(symbol) - mom_12_1(sector_index)
        where mom_12_1 = log(price at t-21 / price at t-252).

        Args:
            symbol_close: Daily close price Series for a single symbol.
                          DatetimeIndex required. Sorted internally.
                          Duplicate timestamps raise ValueError.
            sector_closes: Mapping from sector code to daily close Series of the
                           sector index. The Series for symbol_sector must have a
                           DatetimeIndex. Duplicates raise ValueError.
            symbol_sector: Sector code for this symbol (e.g. "BANK"). If not a
                           key in sector_closes, all rows are NaN.
            rebalance_dates: Rebalance DatetimeIndex. Non-trading dates use the
                   last available close on or before that date.
                   Must be a DatetimeIndex or TypeError is raised.

        Returns:
            DataFrame indexed by rebalance_dates, float32 column
            [sector_rel_strength]. NaN when: len(hist) < 253, symbol_sector not
            in sector_closes, len(sector_hist) < 253, or any boundary price is
            non-positive or NaN.

        Raises:
            TypeError:  If symbol_close.index, rebalance_dates, or the relevant
                        sector Series index is not a DatetimeIndex.
            ValueError: If symbol_close.index or the relevant sector Series index
                        has duplicate timestamps.
        """
        if not isinstance(symbol_close.index, pd.DatetimeIndex):
            raise TypeError("symbol_close must have a DatetimeIndex")
        if not isinstance(rebalance_dates, pd.DatetimeIndex):
            raise TypeError("rebalance_dates must be a DatetimeIndex")
        if symbol_close.index.duplicated().any():
            raise ValueError(
                "symbol_close index contains duplicate timestamps; "
                "de-duplicate before calling compute()"
            )

        symbol_close = symbol_close.sort_index()

        nan_row: dict[str, float] = {s: float("nan") for s in _SIGNAL_NAMES}

        if symbol_sector not in sector_closes:
            result = pd.DataFrame([nan_row] * len(rebalance_dates), index=rebalance_dates)
            return result.astype("float32")

        sector_close: pd.Series = sector_closes[symbol_sector]
        if not isinstance(sector_close.index, pd.DatetimeIndex):
            raise TypeError(
                f"sector_closes['{symbol_sector}'] must have a DatetimeIndex"
            )
        if sector_close.index.duplicated().any():
            raise ValueError(
                f"sector_closes['{symbol_sector}'] index contains duplicate timestamps; "
                "de-duplicate before calling compute()"
            )
        sector_close = sector_close.sort_index()

        rows: list[dict[str, float]] = []
        for t in rebalance_dates:
            hist: pd.Series = symbol_close.loc[symbol_close.index <= t]
            sector_hist: pd.Series = sector_close.loc[sector_close.index <= t]
            row: dict[str, float] = {s: float("nan") for s in _SIGNAL_NAMES}

            if len(hist) >= _MIN_HIST and len(sector_hist) >= _MIN_HIST:
                sym_mom = _mom_12_1(hist)
                sec_mom = _mom_12_1(sector_hist)
                if not (np.isnan(sym_mom) or np.isnan(sec_mom)):
                    row["sector_rel_strength"] = sym_mom - sec_mom

            rows.append(row)

        result = pd.DataFrame(rows, index=rebalance_dates, columns=_SIGNAL_NAMES)
        logger.debug("Computed sector features", extra={"dates": len(rebalance_dates)})
        return result.astype("float32")


__all__: list[str] = ["SectorFeatures"]
