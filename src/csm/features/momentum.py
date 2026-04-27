"""Cross-sectional momentum feature computation."""

import logging

import numpy as np
import pandas as pd

logger: logging.Logger = logging.getLogger(__name__)

# (start_td, end_td): trading-day offsets before rebalance date t.
# price at (t - k trading days) = hist.iloc[-(k+1)].
# end_td=0 means price at t itself = hist.iloc[-1].
_OFFSETS: dict[str, tuple[int, int]] = {
    "mom_12_1": (252, 21),
    "mom_6_1": (126, 21),
    "mom_3_1": (63, 21),
    "mom_1_0": (21, 0),
}

_SIGNAL_NAMES: list[str] = list(_OFFSETS.keys())


def _safe_price(series: pd.Series, iloc_pos: int) -> float:
    """Return the scalar at iloc_pos as float, or NaN if missing or non-positive."""
    raw = series.iloc[iloc_pos]
    if pd.isna(raw):
        return float("nan")
    value = float(raw)
    return value if value > 0.0 else float("nan")


class MomentumFeatures:
    """Compute momentum signals from a single-symbol daily close Series."""

    def compute(
        self,
        close: pd.Series,
        rebalance_dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """Compute all four momentum signals for a single symbol across rebalance dates.

        Signals are computed using integer trading-day offsets counted from the tail of
        available history, so SET public holidays (not on the standard BDay calendar)
        are handled correctly. If a rebalance date is not a trading day, the last
        available close on or before that date is used.

        Args:
            close: Daily close price Series for a single symbol. Must have a DatetimeIndex.
                   The index is sorted internally. Duplicate index values raise ValueError.
                   Non-positive or NaN prices at boundaries produce NaN signals. The
                   timezone of close.index must be compatible with rebalance_dates
                   (mismatches pass through as a pandas TypeError).
            rebalance_dates: Rebalance timestamps (DatetimeIndex) at which features are
                   evaluated.

        Returns:
            DataFrame indexed by rebalance_dates with float32 columns
            [mom_12_1, mom_6_1, mom_3_1, mom_1_0] in that order. NaN when insufficient
            history or a boundary price is invalid.

        Raises:
            TypeError: If close.index or rebalance_dates is not a DatetimeIndex.
            ValueError: If close.index contains duplicate timestamps.
        """
        if not isinstance(close.index, pd.DatetimeIndex):
            raise TypeError("close must have a DatetimeIndex")
        if not isinstance(rebalance_dates, pd.DatetimeIndex):
            raise TypeError("rebalance_dates must be a DatetimeIndex")
        if close.index.duplicated().any():
            raise ValueError(
                "close index contains duplicate timestamps; de-duplicate before calling compute()"
            )

        close = close.sort_index()

        rows: list[dict[str, float]] = []
        for t in rebalance_dates:
            hist: pd.Series = close.loc[close.index <= t]
            n: int = len(hist)
            row: dict[str, float] = {}
            for signal, (start_td, end_td) in _OFFSETS.items():
                if n < start_td + 1:
                    row[signal] = float("nan")
                    continue
                start_price = _safe_price(hist, -(start_td + 1))
                end_iloc = -1 if end_td == 0 else -(end_td + 1)
                end_price = _safe_price(hist, end_iloc)
                if np.isnan(start_price) or np.isnan(end_price):
                    row[signal] = float("nan")
                    continue
                row[signal] = float(np.log(end_price / start_price))
            rows.append(row)

        result: pd.DataFrame = pd.DataFrame(rows, index=rebalance_dates, columns=_SIGNAL_NAMES)
        logger.debug("Computed momentum features", extra={"dates": len(rebalance_dates)})
        return result.astype("float32")


__all__: list[str] = ["MomentumFeatures"]
