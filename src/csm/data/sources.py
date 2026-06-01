"""OHLCV source selection — the ``CSM_OHLCV_SOURCE`` feature flag.

Defines the common :class:`OHLCVSource` protocol shared by the two loaders and
a :func:`build_ohlcv_loader` factory that returns the right one per
``settings.ohlcv_source``:

- ``"parquet"`` (default) — :class:`csm.data.loader.OHLCVLoader`, the unchanged
  legacy path that fetches tvkit and persists the local Parquet store.
- ``"db"`` — :class:`csm.data.engine_loader.MarketDataEngineLoader`, which reads
  pre-fetched bars from the Market Data Engine and never touches tvkit.

Both loaders expose the same ``fetch`` / ``fetch_batch`` surface and return the
identical DataFrame shape, so the routing point (``daily_refresh``) and every
downstream consumer are agnostic to the source.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd

from csm.config.settings import Settings


@runtime_checkable
class OHLCVSource(Protocol):
    """The minimal OHLCV-loader surface consumed by the daily refresh."""

    async def fetch(
        self,
        symbol: str,
        interval: str,
        bars: int,
        adjustment: str | None = None,
    ) -> pd.DataFrame:
        """Fetch a single symbol's OHLCV as a canonical csm DataFrame."""
        ...

    async def fetch_batch(
        self,
        symbols: list[str],
        interval: str,
        bars: int,
        adjustment: str | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Fetch many symbols concurrently; failed symbols are omitted."""
        ...


def build_ohlcv_loader(settings: Settings) -> OHLCVSource:
    """Return the OHLCV loader selected by ``settings.ohlcv_source``.

    Args:
        settings: Application settings carrying the ``ohlcv_source`` flag (and,
            for ``"db"``, the Market Data Engine URL / key).

    Returns:
        An :class:`OHLCVSource`: the legacy tvkit ``OHLCVLoader`` for
        ``"parquet"`` (default), or ``MarketDataEngineLoader`` for ``"db"``.
    """
    # Imported lazily so the legacy path carries no engine-client import cost.
    if settings.ohlcv_source == "db":
        from csm.data.engine_loader import MarketDataEngineLoader

        return MarketDataEngineLoader(settings=settings)

    from csm.data.loader import OHLCVLoader

    return OHLCVLoader(settings=settings)


__all__: list[str] = ["OHLCVSource", "build_ohlcv_loader"]
