"""Information coefficient analysis for signal research."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import pandas as pd

logger: logging.Logger = logging.getLogger(__name__)

_MIN_CROSS_SECTION: int = 10
_MIN_IC_PERIODS: int = 12
_HORIZON_TO_COL: dict[int, str] = {
    1: "fwd_ret_1m",
    2: "fwd_ret_2m",
    3: "fwd_ret_3m",
    6: "fwd_ret_6m",
    12: "fwd_ret_12m",
}


@dataclass
class ICResult:
    """Structured container for a single signal's IC analysis outputs."""

    signal_name: str
    ic_series: pd.Series
    rank_ic_series: pd.Series
    icir: float
    rank_icir: float
    mean_ic: float
    std_ic: float
    t_stat: float
    pct_positive: float
    decay_curve: pd.Series


def _validate_panel(panel_df: object) -> pd.DataFrame:
    if not isinstance(panel_df, pd.DataFrame):
        raise TypeError(f"panel_df must be a pd.DataFrame, got {type(panel_df).__name__}")
    df: pd.DataFrame = panel_df
    if not isinstance(df.index, pd.MultiIndex):
        raise ValueError(f"panel_df.index must be a pd.MultiIndex; got {type(df.index).__name__}")
    if list(df.index.names) != ["date", "symbol"]:
        raise ValueError(
            f"panel_df.index.names must be ['date', 'symbol']; got {list(df.index.names)}"
        )
    return df


class ICAnalyzer:
    """Compute IC, ICIR, and decay diagnostics for panel-based signals."""

    def compute_ic(
        self,
        panel_df: pd.DataFrame,
        signal_col: str,
        forward_ret_col: str,
    ) -> pd.Series:
        """Pearson IC per rebalance date.

        For each date in panel_df, correlates signal_col with forward_ret_col
        across the symbol cross-section (NaN rows dropped pairwise). Returns NaN
        for dates with fewer than _MIN_CROSS_SECTION valid symbol pairs.

        Args:
            panel_df: MultiIndex (date, symbol) panel from FeaturePipeline.
            signal_col: Name of the signal feature column.
            forward_ret_col: Name of the forward return column (e.g. 'fwd_ret_1m').

        Returns:
            pd.Series indexed by rebalance date with Pearson IC values. Name = 'ic'.

        Raises:
            TypeError: If panel_df is not a pd.DataFrame.
            ValueError: If panel_df.index is not a MultiIndex with names
                        ["date", "symbol"], or if a column is missing.
        """
        df = _validate_panel(panel_df)
        for col in (signal_col, forward_ret_col):
            if col not in df.columns:
                raise ValueError(f"{col!r} not found in panel_df columns")

        dates = df.index.get_level_values("date").unique()
        ic_vals: dict[pd.Timestamp, float] = {}
        for date in dates:
            cross = df.xs(date, level="date")[[signal_col, forward_ret_col]].dropna()
            if len(cross) < _MIN_CROSS_SECTION:
                ic_vals[date] = float("nan")
            else:
                ic_vals[date] = float(
                    cross[signal_col].corr(cross[forward_ret_col], method="pearson")
                )
        return pd.Series(ic_vals, name="ic")

    def compute_rank_ic(
        self,
        panel_df: pd.DataFrame,
        signal_col: str,
        forward_ret_col: str,
    ) -> pd.Series:
        """Spearman rank IC per rebalance date.

        Identical contract to compute_ic() except correlation uses Spearman method
        (ranks both signal and return before correlating).

        Returns:
            pd.Series indexed by rebalance date. Name = 'rank_ic'.
        """
        df = _validate_panel(panel_df)
        for col in (signal_col, forward_ret_col):
            if col not in df.columns:
                raise ValueError(f"{col!r} not found in panel_df columns")

        dates = df.index.get_level_values("date").unique()
        ic_vals: dict[pd.Timestamp, float] = {}
        for date in dates:
            cross = df.xs(date, level="date")[[signal_col, forward_ret_col]].dropna()
            if len(cross) < _MIN_CROSS_SECTION:
                ic_vals[date] = float("nan")
            else:
                ic_vals[date] = float(
                    cross[signal_col].corr(cross[forward_ret_col], method="spearman")
                )
        return pd.Series(ic_vals, name="rank_ic")

    def compute_icir(self, ic_series: pd.Series) -> float:
        """Information Coefficient Information Ratio.

        ICIR = mean(IC) / std(IC, ddof=1) over non-NaN observations.
        Returns float('nan') when fewer than _MIN_IC_PERIODS non-NaN
        observations are present or when std == 0.

        Raises:
            TypeError: If ic_series is not a pd.Series.
        """
        if not isinstance(ic_series, pd.Series):
            raise TypeError(f"ic_series must be a pd.Series, got {type(ic_series).__name__}")
        valid = ic_series.dropna()
        if len(valid) < _MIN_IC_PERIODS:
            return float("nan")
        std = float(valid.std(ddof=1))
        if std == 0.0:
            return float("nan")
        return float(valid.mean() / std)

    def compute_decay_curve(
        self,
        panel_df: pd.DataFrame,
        signal_col: str,
        horizons: list[int],
    ) -> pd.Series:
        """Mean Pearson IC by forward horizon.

        For each horizon h in horizons, looks up 'fwd_ret_{h}m' in panel_df
        and computes mean(IC time series). Horizons whose column is absent
        receive NaN.

        Returns:
            pd.Series indexed by horizon integers with mean IC values. Name = 'mean_ic'.
        """
        df = _validate_panel(panel_df)
        if signal_col not in df.columns:
            raise ValueError(f"{signal_col!r} not found in panel_df columns")

        mean_ic: dict[int, float] = {}
        for h in horizons:
            col = _HORIZON_TO_COL.get(h, f"fwd_ret_{h}m")
            if col not in df.columns:
                mean_ic[h] = float("nan")
                continue
            ic_s = self.compute_ic(df, signal_col, col)
            mean_ic[h] = float(ic_s.mean()) if not ic_s.isna().all() else float("nan")
        return pd.Series(mean_ic, name="mean_ic")

    def summary_table(
        self,
        panel_df: pd.DataFrame,
        signal_cols: list[str],
        horizon: int = 1,
    ) -> pd.DataFrame:
        """Aggregated IC statistics table for multiple signals.

        Returns:
            pd.DataFrame indexed by signal name with columns:
              Mean_IC, Std_IC, ICIR, t_stat, pct_positive

        Raises:
            ValueError: If the forward return column for the given horizon
                        is not present in panel_df, or if any signal_col is missing.
        """
        df = _validate_panel(panel_df)
        fwd_col = _HORIZON_TO_COL.get(horizon, f"fwd_ret_{horizon}m")
        if fwd_col not in df.columns:
            raise ValueError(
                f"forward return column {fwd_col!r} for horizon={horizon} not found in panel_df"
            )

        rows: list[dict[str, object]] = []
        for col in signal_cols:
            if col not in df.columns:
                raise ValueError(f"{col!r} not found in panel_df columns")
            ic_s = self.compute_ic(df, col, fwd_col)
            valid = ic_s.dropna()
            mean_ic = float(valid.mean()) if len(valid) > 0 else float("nan")
            std_ic = float(valid.std(ddof=1)) if len(valid) > 1 else float("nan")
            icir = self.compute_icir(ic_s)
            t_val = len(valid)
            t_stat = icir * math.sqrt(t_val) if not math.isnan(icir) and t_val > 0 else float("nan")
            pct_pos = float((valid > 0).mean()) if len(valid) > 0 else float("nan")
            rows.append(
                {
                    "signal": col,
                    "Mean_IC": mean_ic,
                    "Std_IC": std_ic,
                    "ICIR": icir,
                    "t_stat": t_stat,
                    "pct_positive": pct_pos,
                }
            )
        return pd.DataFrame(rows).set_index("signal")


__all__: list[str] = ["ICAnalyzer", "ICResult"]
