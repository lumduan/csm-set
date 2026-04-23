"""Universe construction utilities for csm-set."""

import logging

import pandas as pd

from csm.config.constants import (
    LOOKBACK_YEARS,
    MIN_AVG_DAILY_VOLUME,
    MIN_DATA_COVERAGE,
    MIN_PRICE_THB,
)
from csm.config.settings import Settings
from csm.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)


class UniverseBuilder:
    """Build dated universe snapshots from OHLCV data in a ParquetStore.

    Applies three sequential filters as of a given reference date with no
    look-ahead: price, 90-day trailing volume, and data coverage. Saves one
    parquet snapshot per rebalance date under key ``universe/{YYYY-MM-DD}``.

    Args:
        store: ParquetStore containing symbol OHLCV data (typically ``data/raw/``).
        settings: Application settings. Currently reserved for future extension
            when filter thresholds become env-var configurable. Thresholds are
            sourced from ``constants.py`` in this phase.
    """

    def __init__(self, store: ParquetStore, settings: Settings) -> None:
        self._store = store
        self._settings = settings

    def filter(self, symbol: str, asof: pd.Timestamp) -> bool:
        """Return True if *symbol* passes all filters as of *asof*.

        Uses only data with index ≤ asof — no look-ahead. Returns False
        immediately when no data exists for the symbol.

        Filters applied in order:
        1. Price: latest close ≥ ``MIN_PRICE_THB`` (1 THB)
        2. Volume: 90-day trailing avg volume ≥ ``MIN_AVG_DAILY_VOLUME``
        3. Coverage: valid close bars ≥ ``MIN_DATA_COVERAGE`` within the trailing
           ``LOOKBACK_YEARS * 252`` bar window (or full history if shorter)

        Args:
            symbol: Logical store key (e.g. ``"SET:AOT"``).
            asof: Reference date. Data after this date is excluded.

        Returns:
            True if the symbol passes all filters; False otherwise.
        """
        try:
            df = self._store.load(symbol)
        except KeyError:
            logger.debug("No data for %s — excluded from universe", symbol)
            return False

        history: pd.DataFrame = df[df.index <= _align_tz(asof, df.index)]
        if history.empty:
            return False

        close_series: pd.Series = history["close"]

        # 1. Price filter — latest close ≥ MIN_PRICE_THB
        valid_close = close_series.dropna()
        if valid_close.empty:
            return False
        if float(valid_close.iloc[-1]) < MIN_PRICE_THB:
            return False

        # 2. Volume filter — 90-day trailing avg ≥ MIN_AVG_DAILY_VOLUME
        recent_vol = history.tail(90)["volume"].dropna()
        mean_volume: float = float(recent_vol.mean()) if not recent_vol.empty else 0.0
        if mean_volume < MIN_AVG_DAILY_VOLUME:
            return False

        # 3. Coverage filter — valid bars / window ≥ MIN_DATA_COVERAGE
        # Numerator and denominator both come from the same trailing window so
        # coverage is bounded [0, 1] and old bars outside the window are excluded.
        lookback_window: pd.DataFrame = history.tail(LOOKBACK_YEARS * 252)
        window_size: int = len(lookback_window)
        valid_bars: int = int(lookback_window["close"].notna().sum())
        coverage: float = valid_bars / window_size if window_size > 0 else 0.0
        return coverage >= MIN_DATA_COVERAGE

    def build_snapshot(self, asof: pd.Timestamp, symbols: list[str]) -> list[str]:
        """Return sorted symbols that pass all filters as of *asof*.

        Args:
            asof: Reference date for filter evaluation.
            symbols: Candidate symbols to evaluate.

        Returns:
            Sorted list of symbols passing all filters.
        """
        passing = sorted(s for s in symbols if self.filter(s, asof))
        logger.info(
            "Snapshot %s: %d/%d symbols pass filters",
            asof.strftime("%Y-%m-%d"),
            len(passing),
            len(symbols),
        )
        return passing

    def build_all_snapshots(
        self,
        symbols: list[str],
        rebalance_dates: pd.DatetimeIndex,
        snapshot_store: ParquetStore | None = None,
    ) -> None:
        """Build and persist one snapshot per rebalance date.

        Each snapshot is saved as a DataFrame with ``symbol`` and ``asof``
        columns under key ``universe/{YYYY-MM-DD}``.

        Args:
            symbols: Candidate symbols to evaluate at each date.
            rebalance_dates: Sorted rebalance date index.
            snapshot_store: Store to write snapshots to. Defaults to
                ``self._store`` (same as the OHLCV source) when None.
        """
        out_store = snapshot_store if snapshot_store is not None else self._store
        for date in rebalance_dates:
            passing = self.build_snapshot(date, symbols)
            snapshot_df = pd.DataFrame({"symbol": passing, "asof": date})
            key = f"universe/{date.strftime('%Y-%m-%d')}"
            out_store.save(key, snapshot_df)
            logger.info("Saved %s: %d symbols", key, len(passing))


def _align_tz(asof: pd.Timestamp, index: pd.DatetimeIndex) -> pd.Timestamp:
    """Return *asof* with timezone aligned to *index* to allow scalar comparison.

    Handles four cases:
    - index tz-aware, asof tz-naive → localize asof to index.tz
    - index tz-naive, asof tz-aware → strip asof tz
    - both tz-aware but different zones → convert asof to index.tz
    - same tz (or both tz-naive) → return asof unchanged
    """
    if index.tz is None:
        return asof.replace(tzinfo=None) if asof.tzinfo is not None else asof
    if asof.tzinfo is None:
        return asof.tz_localize(index.tz)
    return asof.tz_convert(index.tz)


__all__: list[str] = ["UniverseBuilder"]
