"""Benchmark (buy-and-hold) equity series loader.

Produces a tz-aware UTC :class:`pandas.Series` of benchmark NAVs normalised
to ``initial_capital`` (so the first observation equals
``initial_capital``). The series feeds the strategy-report's
``benchmark_equity_curve`` field and the ``benchmark_comparison`` table.

Implementation strategy (Phase 1, offline-first):

- Read the benchmark close-price column from the existing
  :class:`csm.data.store.ParquetStore` (the same ``prices_latest`` panel
  the live-portfolio path uses).
- Normalise by dividing through by the first observation and multiplying
  by ``initial_capital``.
- Public mode performs no fetches; if the column is absent the loader
  raises :class:`BenchmarkUnavailableError` and the caller emits the
  report without benchmark fields.

The async signature is preserved for parity with :class:`OHLCVLoader` so
that a future tvkit-backed live fetch path can swap in without changing
callers.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

import pandas as pd

from csm.config.settings import Settings
from csm.data.exceptions import BenchmarkUnavailableError
from csm.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)


class BenchmarkLoader:
    """Load a normalised buy-and-hold equity series for a benchmark symbol."""

    def __init__(self, settings: Settings, store: ParquetStore) -> None:
        """Initialise the loader.

        Args:
            settings: Active csm-set settings — provides ``benchmark_symbol``.
            store: ParquetStore used to read ``prices_latest``.
        """

        self._settings: Settings = settings
        self._store: ParquetStore = store

    async def load(
        self,
        *,
        initial_capital: Decimal,
        start: datetime | None = None,
        end: datetime | None = None,
        prices_key: str = "prices_latest",
    ) -> pd.Series:
        """Return the normalised benchmark NAV series.

        Args:
            initial_capital: NAV at the first observation, in THB.
            start: Inclusive lower bound on the returned index (tz-aware UTC).
            end: Inclusive upper bound on the returned index (tz-aware UTC).
            prices_key: Parquet store key for the price panel. Defaults to
                ``"prices_latest"``.

        Returns:
            ``pd.Series`` of benchmark NAV values, indexed by tz-aware UTC
            ``DatetimeIndex``, named ``benchmark_equity``.

        Raises:
            BenchmarkUnavailableError: When the configured
                ``benchmark_symbol`` column is missing from the prices
                panel, when the prices panel is empty, or when the
                normalised series would be empty after filtering.
        """

        symbol: str = self._settings.benchmark_symbol
        prices: pd.DataFrame = self._store.load(prices_key)
        if prices.empty:
            msg = f"benchmark prices panel '{prices_key}' is empty"
            raise BenchmarkUnavailableError(msg)
        if symbol not in prices.columns:
            msg = (
                f"benchmark column '{symbol}' not found in {prices_key} "
                f"(available columns: {len(prices.columns)})"
            )
            raise BenchmarkUnavailableError(msg)

        prices = self._ensure_utc_index(prices)
        series: pd.Series = prices[symbol].dropna()
        if start is not None:
            series = series.loc[series.index >= pd.Timestamp(start)]
        if end is not None:
            series = series.loc[series.index <= pd.Timestamp(end)]
        if series.empty:
            msg = f"benchmark series for '{symbol}' is empty after applying start={start} end={end}"
            raise BenchmarkUnavailableError(msg)

        first_value: float = float(series.iloc[0])
        if first_value <= 0:
            msg = f"benchmark series first value must be positive, got {first_value}"
            raise BenchmarkUnavailableError(msg)
        scale: float = float(initial_capital) / first_value
        nav: pd.Series = series * scale
        nav.name = "benchmark_equity"
        logger.info(
            "loaded benchmark series symbol=%s n=%d initial_capital=%s",
            symbol,
            len(nav),
            initial_capital,
        )
        return nav

    @staticmethod
    def _ensure_utc_index(frame: pd.DataFrame) -> pd.DataFrame:
        """Coerce a price-panel index to tz-aware UTC (raises if naive without info)."""

        idx: pd.Index = frame.index
        if not isinstance(idx, pd.DatetimeIndex):
            msg = "benchmark prices panel must have a DatetimeIndex"
            raise BenchmarkUnavailableError(msg)
        if idx.tz is None:
            msg = "benchmark prices index is tz-naive; cannot determine UTC alignment"
            raise BenchmarkUnavailableError(msg)
        if str(idx.tz) != "UTC":
            frame = frame.copy()
            frame.index = idx.tz_convert("UTC")
        return frame


__all__: list[str] = ["BenchmarkLoader"]
