"""Risk-adjusted feature computations for csm-set."""

import logging

import numpy as np
import pandas as pd
from scipy import stats

logger: logging.Logger = logging.getLogger(__name__)

# Minimum number of prices in hist (close.loc[<= t]) to compute either signal.
# Derived from 253 prices needed for the 252-return vol/regression window
# (hist.iloc[-274:-21]) plus 21 positions for the skip boundary.
_MIN_HIST: int = 274

# Minimum aligned (symbol, index) return pairs for OLS regression.
_MIN_OLS_PAIRS: int = 63

_SIGNAL_NAMES: list[str] = ["sharpe_momentum", "residual_momentum"]


def _safe_log_returns(prices: np.ndarray) -> np.ndarray:
    """Compute daily log returns from a price array.

    Returns an array of NaN with length len(prices)-1 if any price is <= 0.
    """
    if np.any(prices <= 0):
        return np.full(len(prices) - 1, np.nan)
    return np.diff(np.log(prices))


def _annualised_vol(returns: np.ndarray) -> float:
    """Sample std * sqrt(252). Returns NaN when array has < 2 elements or std == 0."""
    if len(returns) < 2:
        return float("nan")
    vol = float(np.std(returns, ddof=1)) * float(np.sqrt(252.0))
    return vol if vol > 0.0 else float("nan")


def _ols_alpha_annualised(y: np.ndarray, x: np.ndarray) -> float:
    """OLS intercept * 252 via scipy.stats.linregress. Returns NaN if std(x) == 0."""
    if float(np.std(x, ddof=1)) == 0.0:
        return float("nan")
    result = stats.linregress(x, y)
    return float(result.intercept) * 252.0


class RiskAdjustedFeatures:
    """Compute volatility-adjusted and market-neutral momentum signals."""

    def compute(
        self,
        close: pd.Series,
        index_close: pd.Series,
        rebalance_dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """Compute sharpe_momentum and residual_momentum per rebalance date.

        Both signals use a 252-daily-log-return window ending at t-21 (the formation gap
        boundary), derived from hist.iloc[-274:-21] (253 prices). The mom_12_1 numerator
        for sharpe uses the Phase 2.1 formula: log(hist.iloc[-22] / hist.iloc[-253]).

        Args:
            close: Daily close price Series for a single symbol. DatetimeIndex required.
                   Sorted internally. Duplicate timestamps raise ValueError.
            index_close: Daily close for the SET index (e.g. SET:SET). Same timezone
                         convention as close. Duplicate timestamps raise ValueError.
            rebalance_dates: Rebalance DatetimeIndex. Non-trading dates use the last
                   available close on or before that date.

        Returns:
            DataFrame indexed by rebalance_dates, float32 columns
            [sharpe_momentum, residual_momentum]. NaN when insufficient history,
            non-finite vol, non-positive boundary prices, or insufficient OLS data.

        Raises:
            TypeError:  If close.index or index_close.index is not a DatetimeIndex.
            ValueError: If close.index or index_close.index has duplicate timestamps.
        """
        if not isinstance(close.index, pd.DatetimeIndex):
            raise TypeError("close must have a DatetimeIndex")
        if not isinstance(index_close.index, pd.DatetimeIndex):
            raise TypeError("index_close must have a DatetimeIndex")
        if not isinstance(rebalance_dates, pd.DatetimeIndex):
            raise TypeError("rebalance_dates must be a DatetimeIndex")
        if close.index.duplicated().any():
            raise ValueError(
                "close index contains duplicate timestamps; de-duplicate before calling compute()"
            )
        if index_close.index.duplicated().any():
            raise ValueError(
                "index_close index contains duplicate timestamps; "
                "de-duplicate before calling compute()"
            )

        close = close.sort_index()
        index_close = index_close.sort_index()

        rows: list[dict[str, float]] = []
        for t in rebalance_dates:
            hist: pd.Series = close.loc[close.index <= t]
            idx_hist: pd.Series = index_close.loc[index_close.index <= t]
            row: dict[str, float] = {s: float("nan") for s in _SIGNAL_NAMES}

            if len(hist) < _MIN_HIST:
                rows.append(row)
                continue

            # --- sharpe_momentum ---
            prices_slice = hist.iloc[-274:-21]
            rets = _safe_log_returns(prices_slice.values.astype(float))
            vol = _annualised_vol(rets)
            end_p = float(hist.iloc[-22])
            start_p = float(hist.iloc[-253])
            if end_p > 0.0 and start_p > 0.0 and np.isfinite(vol):
                row["sharpe_momentum"] = float(np.log(end_p / start_p)) / vol

            # --- residual_momentum ---
            if len(idx_hist) >= _MIN_HIST:
                sym_slice = hist.iloc[-274:-21]
                idx_slice = idx_hist.reindex(sym_slice.index)
                aligned = pd.concat([sym_slice.rename("s"), idx_slice.rename("i")], axis=1).dropna()
                if len(aligned) >= 2:
                    sym_rets = _safe_log_returns(aligned["s"].values.astype(float))
                    idx_rets = _safe_log_returns(aligned["i"].values.astype(float))
                    if (
                        len(sym_rets) >= _MIN_OLS_PAIRS
                        and not np.any(np.isnan(sym_rets))
                        and not np.any(np.isnan(idx_rets))
                    ):
                        row["residual_momentum"] = _ols_alpha_annualised(y=sym_rets, x=idx_rets)

            rows.append(row)

        result = pd.DataFrame(rows, index=rebalance_dates, columns=_SIGNAL_NAMES)
        logger.debug("Computed risk-adjusted features", extra={"dates": len(rebalance_dates)})
        return result.astype("float32")


__all__: list[str] = ["RiskAdjustedFeatures"]
