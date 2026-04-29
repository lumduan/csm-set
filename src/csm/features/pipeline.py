"""Feature pipeline orchestration for csm-set."""

import logging

import numpy as np
import pandas as pd

from csm.config.settings import Settings
from csm.data.store import ParquetStore
from csm.features.momentum import MomentumFeatures
from csm.features.risk_adjusted import RiskAdjustedFeatures
from csm.features.sector import SectorFeatures

logger: logging.Logger = logging.getLogger(__name__)

_INDEX_SYMBOL: str = "SET:SET"


def _validate_rebalance_dates(rebalance_dates: list[pd.Timestamp]) -> None:
    """Raise ValueError if rebalance_dates is empty, unsorted, or contains duplicates."""
    if not rebalance_dates:
        raise ValueError("rebalance_dates must not be empty")
    for i in range(1, len(rebalance_dates)):
        if rebalance_dates[i] <= rebalance_dates[i - 1]:
            raise ValueError(
                "rebalance_dates must be strictly monotonically increasing and contain no "
                f"duplicates; found {rebalance_dates[i - 1]} >= {rebalance_dates[i]} at "
                f"positions {i - 1} and {i}"
            )


def _validate_prices(prices: dict[str, pd.DataFrame]) -> None:
    """Raise ValueError if any frame in prices fails close-series requirements.

    Each frame must have:
    - a 'close' column
    - a DatetimeIndex on the close Series
    - a monotonically increasing close index
    - a unique (non-duplicate) close index
    """
    for sym, frame in prices.items():
        if "close" not in frame.columns:
            raise ValueError(
                f"prices[{sym!r}] is missing the required 'close' column; "
                f"available columns: {list(frame.columns)}"
            )
        idx = frame["close"].index
        if not isinstance(idx, pd.DatetimeIndex):
            raise ValueError(
                f"prices[{sym!r}]['close'] must have a DatetimeIndex; "
                f"got {type(idx).__name__}"
            )
        if idx.duplicated().any():
            raise ValueError(
                f"prices[{sym!r}]['close'] has duplicate timestamps; "
                "de-duplicate before calling build()"
            )
        if not idx.is_monotonic_increasing:
            raise ValueError(
                f"prices[{sym!r}]['close'] index is not monotonically increasing; "
                "sort before calling build()"
            )


def _validate_panel_df(panel_df: pd.DataFrame) -> None:
    """Raise ValueError if panel_df does not meet the expected MultiIndex contract."""
    if not isinstance(panel_df.index, pd.MultiIndex):
        raise ValueError(
            "panel_df must have a MultiIndex; "
            f"got {type(panel_df.index).__name__}"
        )
    if list(panel_df.index.names) != ["date", "symbol"]:
        raise ValueError(
            "panel_df index names must be ['date', 'symbol']; "
            f"got {list(panel_df.index.names)}"
        )
    if panel_df.index.duplicated().any():
        raise ValueError(
            "panel_df has duplicate (date, symbol) rows; "
            "ensure the panel has a unique index before calling build_forward_returns()"
        )


class FeaturePipeline:
    """Build and persist feature panels used by ranking and backtests."""

    def __init__(
        self,
        store: ParquetStore,
        universe_store: ParquetStore | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._store: ParquetStore = store
        self._universe_store: ParquetStore | None = universe_store
        self._settings: Settings | None = settings
        self._momentum: MomentumFeatures = MomentumFeatures()
        self._risk_adjusted: RiskAdjustedFeatures = RiskAdjustedFeatures()
        self._sector: SectorFeatures = SectorFeatures()
        # Immutable close-series snapshots cached from the last build() call.
        self._last_close_cache: dict[str, pd.Series] = {}
        # Volume snapshots cached from the last build() call (Phase 3.8).
        # Used by build_volume_matrix() to thread volume into the backtest's ADTV filter.
        self._last_volume_cache: dict[str, pd.Series] = {}
        self._last_rebalance_dates: list[pd.Timestamp] = []

    def build(
        self,
        prices: dict[str, pd.DataFrame],
        rebalance_dates: list[pd.Timestamp],
        *,
        symbol_sectors: dict[str, str] | None = None,
    ) -> pd.DataFrame:
        """Build a z-scored, winsorized feature panel across rebalance dates.

        Args:
            prices: Mapping from symbol to OHLCV DataFrames. Every frame must
                    have a 'close' column with a monotonically increasing,
                    duplicate-free DatetimeIndex. Key 'SET:SET' triggers
                    risk-adjusted feature computation.
            rebalance_dates: Strictly monotonically increasing, non-empty list of
                             rebalance timestamps. Raises ValueError on duplicates
                             or unsorted input.
            symbol_sectors: (keyword-only) Optional mapping from symbol to sector
                            code (e.g. "BANK"). When provided, sector_rel_strength
                            is computed per symbol. Symbols with no sector peers in
                            prices receive NaN and are dropped by the NaN filter.

        Returns:
            MultiIndex DataFrame with index (date, symbol). Feature columns are
            float32, winsorized at 1st/99th percentile, and z-scored cross-
            sectionally per date. Per-date symbol candidates are drawn from the
            union of all feature families, reindexed to the global expected schema,
            and then NaN-dropped, so a symbol missing one feature family is dropped
            regardless of which family provided the entry point.
            Returns an empty DataFrame with MultiIndex names ["date", "symbol"]
            and no columns when no valid symbols survive on any date. The result
            (including the empty case) is always persisted via the store.

        Raises:
            ValueError: If prices contains a frame without a 'close' column, with
                        a non-DatetimeIndex, with a non-monotonic or duplicate
                        index; if rebalance_dates is empty, not strictly
                        monotonically increasing, or contains duplicates.
        """
        _validate_prices(prices)
        _validate_rebalance_dates(rebalance_dates)
        dates_index: pd.DatetimeIndex = pd.DatetimeIndex(rebalance_dates)

        index_close: pd.Series | None = None
        if _INDEX_SYMBOL in prices:
            index_close = prices[_INDEX_SYMBOL]["close"]

        # Build equal-weight sector indices from the prices dict.
        sector_index_closes: dict[str, pd.Series] = {}
        if symbol_sectors:
            sector_series_map: dict[str, list[pd.Series]] = {}
            for sym, frame in prices.items():
                if sym == _INDEX_SYMBOL or sym not in symbol_sectors:
                    continue
                code: str = symbol_sectors[sym]
                sector_series_map.setdefault(code, []).append(frame["close"])
            sector_index_closes = {
                code: pd.concat(series_list, axis=1).mean(axis=1)
                for code, series_list in sector_series_map.items()
            }

        # Compute features once per symbol.
        symbol_momentum: dict[str, pd.DataFrame] = {}
        symbol_risk: dict[str, pd.DataFrame] = {}
        symbol_sector_feats: dict[str, pd.DataFrame] = {}

        for symbol, frame in prices.items():
            if symbol == _INDEX_SYMBOL:
                continue
            series: pd.Series = frame["close"].rename(symbol)
            try:
                mom_df: pd.DataFrame = self._momentum.compute(
                    close=series, rebalance_dates=dates_index
                )
                symbol_momentum[symbol] = mom_df
            except (TypeError, ValueError) as exc:
                logger.warning("Skipping momentum for symbol %s: %s", symbol, exc)
            if index_close is not None:
                try:
                    risk_df: pd.DataFrame = self._risk_adjusted.compute(
                        close=series,
                        index_close=index_close,
                        rebalance_dates=dates_index,
                    )
                    symbol_risk[symbol] = risk_df
                except (TypeError, ValueError) as exc:
                    logger.warning(
                        "Skipping risk-adjusted features for symbol %s: %s", symbol, exc
                    )
            if symbol_sectors and symbol in symbol_sectors and sector_index_closes:
                try:
                    sector_df: pd.DataFrame = self._sector.compute(
                        symbol_close=series,
                        sector_closes=sector_index_closes,
                        symbol_sector=symbol_sectors[symbol],
                        rebalance_dates=dates_index,
                    )
                    symbol_sector_feats[symbol] = sector_df
                except (TypeError, ValueError) as exc:
                    logger.warning("Skipping sector features for symbol %s: %s", symbol, exc)

        # Determine the global expected feature schema from successfully computed families.
        # Per-date rows are reindexed to this schema before dropna() so that a symbol
        # missing one family is dropped even when not discovered via that family's dict.
        expected_cols: list[str] = []
        if symbol_momentum:
            expected_cols += list(next(iter(symbol_momentum.values())).columns)
        if index_close is not None and symbol_risk:
            expected_cols += list(next(iter(symbol_risk.values())).columns)
        if symbol_sectors and symbol_sector_feats:
            expected_cols += list(next(iter(symbol_sector_feats.values())).columns)

        # Candidate symbol set per date: union of all feature families.
        all_symbols: set[str] = set(symbol_momentum) | set(symbol_risk) | set(symbol_sector_feats)

        panel_frames: list[pd.DataFrame] = []
        for rebalance_date in rebalance_dates:
            date_rows: list[dict[str, object]] = []
            for symbol in all_symbols:
                row: dict[str, object] = {"symbol": symbol}
                if symbol in symbol_momentum and rebalance_date in symbol_momentum[symbol].index:
                    row.update(symbol_momentum[symbol].loc[rebalance_date].to_dict())
                if symbol in symbol_risk and rebalance_date in symbol_risk[symbol].index:
                    row.update(symbol_risk[symbol].loc[rebalance_date].to_dict())
                if (
                    symbol in symbol_sector_feats
                    and rebalance_date in symbol_sector_feats[symbol].index
                ):
                    row.update(symbol_sector_feats[symbol].loc[rebalance_date].to_dict())
                if len(row) > 1:
                    date_rows.append(row)

            if not date_rows:
                continue

            feature_frame: pd.DataFrame = (
                pd.DataFrame(date_rows)
                .set_index("symbol")
                .reindex(columns=expected_cols)  # enforces global schema; adds NaN where absent
            )

            n_before: int = len(feature_frame)
            feature_frame = feature_frame.dropna()
            n_dropped: int = n_before - len(feature_frame)
            if n_dropped > 0:
                logger.info(
                    "Dropped %d symbols with NaN features on %s", n_dropped, rebalance_date
                )
            if feature_frame.empty:
                logger.warning("No valid symbols on %s after NaN drop", rebalance_date)
                continue

            winsorised: pd.DataFrame = feature_frame.copy()
            for column in expected_cols:
                if column not in winsorised.columns:
                    continue
                lower: float = float(winsorised[column].quantile(0.01))
                upper: float = float(winsorised[column].quantile(0.99))
                winsorised[column] = winsorised[column].clip(lower=lower, upper=upper)
                std: float = float(winsorised[column].std(ddof=0))
                mean: float = float(winsorised[column].mean())
                winsorised[column] = (
                    0.0 if std == 0.0 else (winsorised[column] - mean) / std
                )

            winsorised = winsorised.astype("float32")
            winsorised["date"] = rebalance_date
            panel_frames.append(winsorised.reset_index(names="symbol"))

        # Cache immutable close-series snapshots for build_forward_returns().
        self._last_close_cache = {sym: frame["close"].copy() for sym, frame in prices.items()}
        # Cache volume snapshots for build_volume_matrix() (Phase 3.8 — ADTV filter).
        self._last_volume_cache = {
            sym: frame["volume"].copy()
            for sym, frame in prices.items()
            if "volume" in frame.columns
        }
        self._last_rebalance_dates = list(rebalance_dates)

        if not panel_frames:
            empty_index: pd.MultiIndex = pd.MultiIndex.from_arrays(
                [[], []], names=["date", "symbol"]
            )
            panel: pd.DataFrame = pd.DataFrame(index=empty_index)
            # Persist the empty result so load_latest() does not return stale data.
            self._store.save(key="features_latest", df=panel.reset_index())
            return panel

        panel = pd.concat(panel_frames, ignore_index=True)
        panel = panel.set_index(["date", "symbol"]).sort_index()
        self._store.save(key="features_latest", df=panel.reset_index())
        logger.info("Built feature panel with %d rows", len(panel.index))
        return panel

    def build_forward_returns(
        self,
        panel_df: pd.DataFrame,
        horizons: list[int],
        prices: dict[str, pd.DataFrame] | None = None,
        rebalance_dates: list[pd.Timestamp] | None = None,
    ) -> pd.DataFrame:
        """Compute forward log returns and join them to panel_df.

        Forward returns are anchored to an explicit rebalance calendar to prevent
        horizon drift when dates are absent from the panel (e.g. all symbols NaN).
        Callers that built the panel from a fresh instance or a different build()
        call must supply rebalance_dates explicitly.

        Safe to call multiple times: existing fwd_ret_* columns matching the
        requested horizons are dropped and recomputed.

        Args:
            panel_df: MultiIndex (date, symbol) panel produced by build(). Must
                      have a MultiIndex with names ['date', 'symbol'] and a unique
                      index.
            horizons: Non-empty list of positive integer horizon numbers in months,
                      e.g. [1, 2, 3, 6, 12]. Duplicates raise ValueError.
                      For horizon h, fwd_ret_{h}m = log(close[t+h] / close[t])
                      where t and t+h are consecutive entries in the rebalance
                      calendar.
            prices: OHLCV dict keyed by symbol. Must contain all symbols in
                    panel_df with valid 'close' DatetimeIndex series. Must be
                    provided when no build() has been called on this instance.
            rebalance_dates: Explicit rebalance calendar to use as the horizon
                             anchor. Must contain all dates present in panel_df.
                             When None, uses the calendar from the last build()
                             call.

        Returns:
            panel_df extended with float32 columns fwd_ret_{h}m for each h in
            horizons (in the order given). Values are raw log returns, not z-scored.
            NaN when the h-th future rebalance date does not exist in the calendar,
            or when the close price is missing at either anchor date.
            When panel_df is empty, returns a copy with the forward-return columns
            added (all NaN, float32) without requiring cached calendar or prices.

        Raises:
            ValueError: If panel_df does not have the required MultiIndex structure
                        or has duplicate rows; if horizons is empty, contains
                        non-positive values, or contains duplicates; if
                        rebalance_dates is None and no prior build() was called;
                        if prices is None and no prior build() was called; if
                        panel dates are absent from the rebalance calendar; or if
                        panel symbols are absent from prices.
        """
        _validate_panel_df(panel_df)

        if not horizons:
            raise ValueError("horizons must not be empty")
        if any(h < 1 for h in horizons):
            raise ValueError("all horizons must be positive integers (>= 1)")
        if len(horizons) != len(set(horizons)):
            raise ValueError("horizons must not contain duplicates")

        fwd_cols: list[str] = [f"fwd_ret_{h}m" for h in horizons]

        # Drop any pre-existing fwd_ret columns so repeated calls are safe.
        existing_fwd: list[str] = [c for c in fwd_cols if c in panel_df.columns]
        base_df: pd.DataFrame = panel_df.drop(columns=existing_fwd) if existing_fwd else panel_df

        # Empty-panel fast path: return a copy with NaN forward-return columns
        # without requiring cached calendar or prices to be available.
        if base_df.empty:
            empty_fwd: pd.DataFrame = pd.DataFrame(
                float("nan"), index=base_df.index, columns=fwd_cols, dtype="float32"
            )
            return base_df.join(other=empty_fwd, how="left")

        # Resolve and validate the rebalance calendar.
        rebal_cal: list[pd.Timestamp]
        if rebalance_dates is not None:
            _validate_rebalance_dates(rebalance_dates)
            rebal_cal = list(rebalance_dates)
        else:
            if not self._last_rebalance_dates:
                raise ValueError(
                    "No rebalance calendar is available. Either pass rebalance_dates "
                    "explicitly or call build() before build_forward_returns()."
                )
            rebal_cal = self._last_rebalance_dates

        # Resolve and validate the prices / close-series map.
        close_map: dict[str, pd.Series]
        if prices is not None:
            _validate_prices(prices)
            close_map = {sym: frame["close"] for sym, frame in prices.items()}
        else:
            if not self._last_close_cache:
                raise ValueError(
                    "No price data is available. Either pass prices explicitly or call "
                    "build() before build_forward_returns()."
                )
            close_map = self._last_close_cache

        # Validate that all panel dates are covered by the rebalance calendar.
        cal_set: set[pd.Timestamp] = set(rebal_cal)
        panel_dates: set[pd.Timestamp] = set(
            base_df.index.get_level_values("date").unique().tolist()
        )
        missing_dates: set[pd.Timestamp] = panel_dates - cal_set
        if missing_dates:
            raise ValueError(
                "panel_df contains dates not present in the rebalance calendar; "
                f"missing: {sorted(missing_dates)}"
            )

        # Validate that all panel symbols are present in close_map.
        panel_symbols: set[object] = set(
            base_df.index.get_level_values("symbol").unique().tolist()
        )
        missing_symbols: set[object] = panel_symbols - set(close_map)
        if missing_symbols:
            raise ValueError(
                "panel_df contains symbols not present in prices; "
                f"missing: {sorted(str(s) for s in missing_symbols)}"
            )

        n_cal: int = len(rebal_cal)
        cal_pos: dict[pd.Timestamp, int] = {t: i for i, t in enumerate(rebal_cal)}

        fwd_rows: list[dict[str, object]] = []
        for symbol, sym_group in base_df.groupby(level="symbol"):
            close: pd.Series = close_map[symbol].sort_index()

            # Close price at each calendar date (last available if non-trading).
            rebal_closes: dict[pd.Timestamp, float] = {}
            for t in rebal_cal:
                hist: pd.Series = close.loc[close.index <= t]
                rebal_closes[t] = float(hist.iloc[-1]) if len(hist) > 0 else float("nan")

            for t in sym_group.index.get_level_values("date"):
                row: dict[str, object] = {"date": t, "symbol": symbol}
                i: int = cal_pos[t]  # guaranteed by earlier validation
                p0: float = rebal_closes.get(t, float("nan"))
                for h in horizons:
                    col: str = f"fwd_ret_{h}m"
                    if i + h < n_cal:
                        t_future: pd.Timestamp = rebal_cal[i + h]
                        p1: float = rebal_closes.get(t_future, float("nan"))
                        if not (np.isnan(p0) or np.isnan(p1) or p0 <= 0.0 or p1 <= 0.0):
                            row[col] = float(np.log(p1 / p0))
                        else:
                            row[col] = float("nan")
                    else:
                        row[col] = float("nan")
                fwd_rows.append(row)

        fwd_frame: pd.DataFrame = (
            pd.DataFrame(fwd_rows)
            .set_index(["date", "symbol"])[fwd_cols]
            .astype("float32")
        )
        return base_df.join(other=fwd_frame, how="left")

    def load_latest(self) -> pd.DataFrame:
        """Load the latest persisted feature panel from the store."""
        latest: pd.DataFrame = self._store.load(key="features_latest")
        latest["date"] = pd.to_datetime(latest["date"])
        return latest.set_index(["date", "symbol"]).sort_index()

    def build_volume_matrix(self, exclude: tuple[str, ...] = (_INDEX_SYMBOL,)) -> pd.DataFrame:
        """Return wide volume matrix from the last build() call (Phase 3.8).

        The matrix has a DatetimeIndex (union of per-symbol indices) and one
        float column per stock symbol, ready to pass to
        ``MomentumBacktest.run(..., volumes=...)`` so the ADTV hard filter
        actually fires.

        Args:
            exclude: Symbols to drop from the matrix (defaults to the SET index
                     itself, since ADTV applies to stocks only).

        Returns:
            Sorted, ascending-DatetimeIndex DataFrame. Empty when build() has
            not been called or no symbol exposed a 'volume' column — caller
            should treat empty as a hard error since the ADTV filter is
            essential to the backtest's universe.
        """
        if not self._last_volume_cache:
            logger.warning(
                "build_volume_matrix() called but volume cache is empty — "
                "rebuild the feature panel from OHLCV frames containing 'volume'",
            )
            return pd.DataFrame()
        cols: dict[str, pd.Series] = {
            sym: series for sym, series in self._last_volume_cache.items() if sym not in exclude
        }
        if not cols:
            return pd.DataFrame()
        matrix: pd.DataFrame = pd.DataFrame(cols)
        matrix.index = pd.to_datetime(matrix.index)
        return matrix.sort_index()


__all__: list[str] = ["FeaturePipeline"]
