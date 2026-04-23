"""Per-symbol OHLCV price-cleaning utilities."""

import logging

import pandas as pd

from csm.config.constants import MIN_DATA_COVERAGE

logger: logging.Logger = logging.getLogger(__name__)


class PriceCleaner:
    """Clean per-symbol OHLCV DataFrames for downstream signal calculations.

    All methods are pure transforms — no I/O, no state. Each method accepts and
    returns a DataFrame conforming to the OHLCV schema (DatetimeIndex + open, high,
    low, close, volume columns). ``clean()`` returns ``None`` when the symbol is
    dropped by the coverage check.
    """

    def forward_fill_gaps(
        self,
        df: pd.DataFrame,
        max_gap_days: int = 5,
    ) -> pd.DataFrame:
        """Forward-fill NaN values for gaps of ≤ *max_gap_days* consecutive rows.

        Gaps larger than *max_gap_days* are left as NaN. Applies to all OHLCV
        columns so rows remain internally consistent.

        Args:
            df: Per-symbol OHLCV DataFrame.
            max_gap_days: Maximum consecutive NaN rows to fill. Default 5.

        Returns:
            DataFrame with short gaps filled.
        """
        return df.ffill(limit=max_gap_days)

    def drop_low_coverage(
        self,
        df: pd.DataFrame,
        min_coverage: float = MIN_DATA_COVERAGE,
        window_years: int = 1,
    ) -> pd.DataFrame | None:
        """Return ``None`` if any rolling year has insufficient close coverage.

        Checks every ``window_years * 252``-bar rolling window. If any window has
        more than ``(1 - min_coverage)`` fraction of NaN close bars, the symbol is
        dropped. For DataFrames shorter than one full window, the entire history is
        checked instead.

        Args:
            df: Per-symbol OHLCV DataFrame.
            min_coverage: Minimum fraction of valid (non-NaN) close bars. Default 0.80.
            window_years: Rolling window length in trading years (252 bars each).

        Returns:
            The original DataFrame if coverage is sufficient; ``None`` if dropped.
        """
        window_size = window_years * 252
        close = df["close"]

        if len(close) < window_size:
            total = len(close)
            valid = int(close.notna().sum())
            if total == 0 or valid / total < min_coverage:
                logger.debug("Insufficient coverage over short history — dropping symbol")
                return None
            return df

        nan_count = close.isna().rolling(window_size, min_periods=window_size).sum()
        max_missing_allowed = window_size * (1.0 - min_coverage)

        if float(nan_count.max()) > max_missing_allowed:
            logger.debug(
                "Rolling coverage check failed (max NaN in window: %.0f > %.1f) — dropping symbol",
                float(nan_count.max()),
                max_missing_allowed,
            )
            return None
        return df

    def winsorise_returns(
        self,
        df: pd.DataFrame,
        lower: float = 0.01,
        upper: float = 0.99,
    ) -> pd.DataFrame:
        """Clip extreme daily close returns and back-compute the close series.

        Computes arithmetic daily returns from ``close``, clips them at the
        [*lower*, *upper*] percentile bounds, then reconstructs the full close
        series from the first valid close using the clipped returns. Only ``close``
        is modified; other columns are unchanged.

        Args:
            df: Per-symbol OHLCV DataFrame.
            lower: Lower percentile bound for clipping (e.g. 0.01 = 1st percentile).
            upper: Upper percentile bound for clipping (e.g. 0.99 = 99th percentile).

        Returns:
            DataFrame with extreme close values replaced.
        """
        result = df.copy()
        close = result["close"]

        returns = close.pct_change()
        lower_bound = float(returns.quantile(lower))
        upper_bound = float(returns.quantile(upper))
        clipped = returns.clip(lower=lower_bound, upper=upper_bound)

        new_close = close.copy()
        for i in range(1, len(close)):
            prev = new_close.iloc[i - 1]
            r = clipped.iloc[i]
            if pd.notna(prev) and pd.notna(r):
                new_close.iloc[i] = prev * (1.0 + r)

        result["close"] = new_close
        return result

    def clean(self, df: pd.DataFrame) -> pd.DataFrame | None:
        """Apply the full cleaning pipeline to a per-symbol OHLCV DataFrame.

        Steps applied in order:
        1. ``forward_fill_gaps`` — fill short NaN gaps (≤ 5 consecutive days)
        2. ``drop_low_coverage`` — return ``None`` if any rolling year has < 80% valid bars
        3. ``winsorise_returns`` — clip extreme close returns at 1st/99th percentile

        Args:
            df: Per-symbol OHLCV DataFrame.

        Returns:
            Cleaned DataFrame, or ``None`` if the symbol is dropped by coverage check.
        """
        filled = self.forward_fill_gaps(df)
        covered = self.drop_low_coverage(filled)
        if covered is None:
            return None
        return self.winsorise_returns(covered)


__all__: list[str] = ["PriceCleaner"]
