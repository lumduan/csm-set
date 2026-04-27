"""Cross-sectional ranking utilities for signal research."""

import logging

import pandas as pd

logger: logging.Logger = logging.getLogger(__name__)

_SKIP_PREFIXES: tuple[str, ...] = ("fwd_ret_",)
_SKIP_SUFFIXES: tuple[str, ...] = ("_rank", "_quintile")


def _validate_panel(panel_df: object) -> pd.DataFrame:
    if not isinstance(panel_df, pd.DataFrame):
        raise TypeError(f"panel_df must be a pd.DataFrame, got {type(panel_df).__name__}")
    df: pd.DataFrame = panel_df
    if not isinstance(df.index, pd.MultiIndex):
        raise ValueError(
            f"panel_df.index must be a pd.MultiIndex; got {type(df.index).__name__}"
        )
    if list(df.index.names) != ["date", "symbol"]:
        raise ValueError(
            f"panel_df.index.names must be ['date', 'symbol']; got {list(df.index.names)}"
        )
    return df


def _assign_quintiles(
    ranks: pd.Series,
    *,
    signal_col: str = "",
    date: object = None,
) -> pd.Series:
    """Assign quintile labels 1–5 to a percentile rank Series.

    Falls back to sparse integer labels (e.g. 1, 3, 5) when fewer than 5 unique bin
    edges are available. Returns all-NaN Int8 Series only when binning fails entirely.
    """
    try:
        return pd.qcut(ranks, q=5, labels=[1, 2, 3, 4, 5], duplicates="drop").astype("Int8")
    except ValueError:
        pass
    try:
        bins: pd.Series = pd.qcut(ranks, q=5, labels=False, duplicates="drop")
        n_bins: int = int(bins.max()) + 1
        label_map: dict[int, int] = {
            i: int(round(1 + i * 4 / max(n_bins - 1, 1))) for i in range(n_bins)
        }
        return bins.map(label_map).astype("Int8")
    except ValueError:
        logger.warning(
            "Cannot assign quintiles for signal %r on date %s (cross-section size %d); "
            "returning NaN",
            signal_col,
            date,
            len(ranks),
        )
        return pd.Series(pd.NA, index=ranks.index, dtype="Int8")


def _rank_inplace(df: pd.DataFrame, signal_col: str) -> None:
    """Append rank and quintile columns for signal_col to df in-place.

    Operates directly on df without creating an extra copy. Called by rank() (which owns
    the copy) and rank_all() (which creates one shared copy for all columns).
    """
    rank_col = f"{signal_col}_rank"
    quintile_col = f"{signal_col}_quintile"
    df[rank_col] = float("nan")
    df[quintile_col] = pd.array([pd.NA] * len(df), dtype="Int8")

    for date in df.index.get_level_values("date").unique():
        mask = df.index.get_level_values("date") == date
        values: pd.Series = df.loc[mask, signal_col]
        valid: pd.Series = values.dropna()
        if valid.empty:
            continue
        ranks: pd.Series = valid.rank(method="average", pct=True)
        df.loc[valid.index, rank_col] = ranks
        df.loc[valid.index, quintile_col] = _assign_quintiles(
            ranks, signal_col=signal_col, date=date
        )


class CrossSectionalRanker:
    """Rank symbols cross-sectionally within each rebalance date."""

    def rank(self, panel_df: pd.DataFrame, signal_col: str) -> pd.DataFrame:
        """Compute cross-sectional percentile rank and quintile label for one signal.

        For each date in panel_df, ranks symbols by `signal_col` within that date's
        cross-section. Symbols with NaN in `signal_col` are excluded from ranking on that
        date and receive NaN in the output rank/quintile columns.

        Args:
            panel_df: MultiIndex (date, symbol) panel produced by FeaturePipeline.
                      Index must be a pd.MultiIndex with names ["date", "symbol"].
            signal_col: Name of the feature column to rank.

        Returns:
            Copy of panel_df with two additional columns:
              - `{signal_col}_rank`: float64, percentile rank in (0, 1].
                Ties resolved with method='average'.
              - `{signal_col}_quintile`: Int8 (nullable), quintile label 1–5.
                NaN for excluded (NaN-signal) symbols. For very small or highly
                tied cross-sections the fallback may produce non-contiguous labels
                (e.g. 1, 3, 5). NaN is returned only when binning fails entirely.

        Raises:
            TypeError: If panel_df is not a pd.DataFrame.
            ValueError: If panel_df.index is not a pd.MultiIndex with names
                        ["date", "symbol"], or if signal_col is not a column in panel_df.
        """
        df = _validate_panel(panel_df)
        if signal_col not in df.columns:
            raise ValueError(
                f"signal_col {signal_col!r} not found in panel_df columns; "
                f"available: {list(df.columns)}"
            )
        result = df.copy()
        _rank_inplace(result, signal_col)
        return result

    def rank_all(self, panel_df: pd.DataFrame) -> pd.DataFrame:
        """Apply rank() to every numeric feature column in panel_df.

        Skips forward-return columns (names starting with 'fwd_ret_') and columns that
        already end with '_rank' or '_quintile'. Ranks only numeric dtypes.

        Creates one copy of panel_df and appends all rank/quintile columns in-place on
        that copy — no redundant per-column copies.

        Args:
            panel_df: MultiIndex (date, symbol) panel produced by FeaturePipeline.

        Returns:
            Copy of panel_df with rank and quintile columns for every qualifying feature.

        Raises:
            TypeError: If panel_df is not a pd.DataFrame.
            ValueError: If panel_df.index is not a pd.MultiIndex with names
                        ["date", "symbol"].
        """
        df = _validate_panel(panel_df)
        result = df.copy()
        numeric_cols: list[str] = df.select_dtypes(include="number").columns.tolist()
        for col in numeric_cols:
            if any(col.startswith(p) for p in _SKIP_PREFIXES):
                continue
            if any(col.endswith(s) for s in _SKIP_SUFFIXES):
                continue
            _rank_inplace(result, col)
        return result


__all__: list[str] = ["CrossSectionalRanker"]
