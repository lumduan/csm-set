"""Drawdown and run-up analysis helpers."""

from __future__ import annotations

import logging

import pandas as pd

logger: logging.Logger = logging.getLogger(__name__)


class DrawdownAnalyzer:
    """Compute drawdown / run-up series and their episode tables."""

    def max_drawdown(self, equity_curve: pd.Series) -> float:
        """Return the maximum drawdown as a negative float."""

        underwater: pd.Series = self.underwater_curve(equity_curve)
        return float(underwater.min())

    def underwater_curve(self, equity_curve: pd.Series) -> pd.Series:
        """Return the drawdown from the running peak."""

        return equity_curve / equity_curve.cummax() - 1.0

    def rolling_drawdown(self, equity: pd.Series, window: int) -> pd.Series:
        """Compute rolling N-period drawdown relative to the trailing peak.

        For each point, the rolling max is taken over the *window* most recent
        observations.  The drawdown is ``equity / rolling_max - 1``.  This is
        *not* the peak-to-trough max DD — once a trough rolls out of the
        window, the rolling drawdown recovers naturally.

        Args:
            equity: Equity curve as a monotonically-indexed Series.
            window: Lookback window in periods (e.g., 60 for 60-day rolling).

        Returns:
            Series of the same length as *equity* with values in (−1, 0].
        """
        if equity.empty:
            return pd.Series(dtype=float)

        rolling_max: pd.Series = equity.rolling(window=window, min_periods=1).max()
        return equity / rolling_max - 1.0

    def recovery_periods(self, equity_curve: pd.Series) -> pd.DataFrame:
        """Identify drawdown and recovery episodes."""

        underwater: pd.Series = self.underwater_curve(equity_curve)
        rows: list[dict[str, object]] = []
        in_drawdown: bool = False
        start: pd.Timestamp | None = None
        trough: pd.Timestamp | None = None
        trough_depth: float = 0.0
        for date, value in underwater.items():
            if value < 0.0 and not in_drawdown:
                in_drawdown = True
                start = pd.Timestamp(date)
                trough = pd.Timestamp(date)
                trough_depth = float(value)
            elif value < trough_depth and in_drawdown:
                trough = pd.Timestamp(date)
                trough_depth = float(value)
            elif value >= 0.0 and in_drawdown and start is not None and trough is not None:
                recovery: pd.Timestamp = pd.Timestamp(date)
                duration_days = int((recovery - start).days)
                rows.append(
                    {
                        "start": start,
                        "trough": trough,
                        "recovery": recovery,
                        "depth": trough_depth,
                        "duration_days": duration_days,
                        "recovery_months": round(duration_days / 30.5, 1),
                    }
                )
                in_drawdown = False
        return pd.DataFrame(rows)

    def runup_curve(self, equity_curve: pd.Series) -> pd.Series:
        """Return the run-up (above-trough) curve as a fraction of the running trough.

        Mirror of :meth:`underwater_curve` with the running minimum replacing
        the running maximum: each point measures how far above the
        running-trough the equity has risen.
        """

        return equity_curve / equity_curve.cummin() - 1.0

    def runup_episodes(self, equity_curve: pd.Series) -> pd.DataFrame:
        """Identify run-up episodes — peaks above the running trough.

        Mirrors :meth:`recovery_periods` with the underwater sign inverted.
        A run-up episode begins when the equity rises above the most recent
        trough and ends when the equity returns to that trough (or below).

        Args:
            equity_curve: Monotonically-indexed equity series. Empty input
                returns an empty DataFrame with the documented columns.

        Returns:
            DataFrame with columns ``start``, ``peak``, ``end``, ``height``,
            ``duration_days``, ``height_months``. ``height`` is the
            fractional peak-over-trough excursion.
        """

        runup: pd.Series = self.runup_curve(equity_curve)
        rows: list[dict[str, object]] = []
        in_runup: bool = False
        start: pd.Timestamp | None = None
        peak_time: pd.Timestamp | None = None
        peak_height: float = 0.0
        for date, value in runup.items():
            if value > 0.0 and not in_runup:
                in_runup = True
                start = pd.Timestamp(date)
                peak_time = pd.Timestamp(date)
                peak_height = float(value)
            elif value > peak_height and in_runup:
                peak_time = pd.Timestamp(date)
                peak_height = float(value)
            elif value <= 0.0 and in_runup and start is not None and peak_time is not None:
                end: pd.Timestamp = pd.Timestamp(date)
                duration_days = int((end - start).days)
                rows.append(
                    {
                        "start": start,
                        "peak": peak_time,
                        "end": end,
                        "height": peak_height,
                        "duration_days": duration_days,
                        "height_months": round(duration_days / 30.5, 1),
                    }
                )
                in_runup = False
        return pd.DataFrame(rows)

    def max_runup(self, equity_curve: pd.Series) -> float:
        """Maximum run-up as a positive fraction; ``0.0`` on empty or all-falling input."""

        runup: pd.Series = self.runup_curve(equity_curve)
        if runup.empty:
            return 0.0
        return float(runup.max())

    def max_runup_pct(self, equity_curve: pd.Series) -> float:
        """Alias for :meth:`max_runup` (kept for parity with `max_drawdown` semantics)."""

        return self.max_runup(equity_curve)

    def avg_runup_duration(self, equity_curve: pd.Series) -> float:
        """Mean ``duration_days`` across detected run-up episodes; ``0.0`` when none."""

        episodes: pd.DataFrame = self.runup_episodes(equity_curve)
        if episodes.empty:
            return 0.0
        return float(episodes["duration_days"].mean())

    def avg_runup_pct(self, equity_curve: pd.Series) -> float:
        """Mean ``height`` across detected run-up episodes; ``0.0`` when none."""

        episodes: pd.DataFrame = self.runup_episodes(equity_curve)
        if episodes.empty:
            return 0.0
        return float(episodes["height"].mean())


__all__: list[str] = ["DrawdownAnalyzer"]
