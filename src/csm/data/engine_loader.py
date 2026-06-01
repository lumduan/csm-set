"""OHLCV loading backed by the Market Data Engine read API.

``MarketDataEngineLoader`` is a drop-in alternative to
:class:`csm.data.loader.OHLCVLoader` selected when ``CSM_OHLCV_SOURCE='db'``.
It reads pre-fetched bars from the Market Data Engine
(``quant-marketdata-engine``) over HTTP instead of fetching tvkit directly,
and returns the **identical** DataFrame shape so every downstream consumer
(features, research, portfolio) is unchanged:

    columns ``["open", "high", "low", "close", "volume"]`` (float), indexed by
    a ``DatetimeIndex`` (timezone ``Asia/Bangkok``, name ``"datetime"``),
    sorted ascending; a zero-row frame with that schema when the engine
    returns no bars.

This loader holds **no tvkit credential** — the engine is the sole
cookie owner (feature-market-data-engine Phase 3).
"""

from __future__ import annotations

import asyncio
import logging

import pandas as pd

from csm.adapters.market_data_engine_client import (
    EngineOHLCVResponse,
    MarketDataEngineClient,
    MarketDataEngineError,
)
from csm.config.constants import TIMEZONE
from csm.config.settings import Settings
from csm.data.exceptions import DataAccessError, EngineReadError
from csm.data.loader import Adjustment

logger: logging.Logger = logging.getLogger(__name__)

_OHLCV_COLUMNS: list[str] = ["open", "high", "low", "close", "volume"]

# csm uses tvkit interval strings (e.g. "1D"); the engine uses lowercase
# ("1d"/"1h"/"5m"). Normalisation is a simple case-fold, validated below.
_ENGINE_TIMEFRAMES: frozenset[str] = frozenset({"1d", "1h", "5m"})


class MarketDataEngineLoader:
    """Read OHLCV from the Market Data Engine, matching ``OHLCVLoader``'s API.

    Args:
        settings: Application settings. Requires ``market_data_engine_base_url``
            when used (guaranteed by the ``ohlcv_source='db'`` settings
            validator); ``market_data_engine_api_key`` is optional.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings: Settings = settings
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(settings.tvkit_concurrency)

    def _build_client(self) -> MarketDataEngineClient:
        base_url: str | None = self._settings.market_data_engine_base_url
        if not base_url:
            # Defensive: the Settings validator already enforces this for db source.
            raise EngineReadError(
                "market_data_engine_base_url is not configured; set "
                "CSM_MARKET_DATA_ENGINE_BASE_URL to read from the Market Data Engine."
            )
        api_key: str | None = (
            self._settings.market_data_engine_api_key.get_secret_value()
            if self._settings.market_data_engine_api_key is not None
            else None
        )
        return MarketDataEngineClient(base_url=base_url, api_key=api_key)

    @staticmethod
    def _resolve(
        interval: str, adjustment: str | None, default_adjustment: str
    ) -> tuple[str, bool]:
        """Map csm ``(interval, adjustment)`` to engine ``(timeframe, adjusted)``.

        Raises ``ValueError`` on an unsupported interval or adjustment, before
        any network I/O — mirroring ``OHLCVLoader``'s fail-fast contract.
        """
        timeframe: str = interval.strip().lower()
        if timeframe not in _ENGINE_TIMEFRAMES:
            raise ValueError(
                f"interval {interval!r} maps to timeframe {timeframe!r}, which the "
                f"Market Data Engine does not support (expected one of "
                f"{sorted(_ENGINE_TIMEFRAMES)!r})."
            )
        effective: str = adjustment if adjustment is not None else default_adjustment
        # Validate via the shared enum: raises ValueError on unknown modes.
        mode: Adjustment = Adjustment(effective)
        # 'dividends' -> adjust-on-read endpoint; 'splits' -> raw (split-adjusted base).
        adjusted: bool = mode is Adjustment.DIVIDENDS
        return timeframe, adjusted

    @staticmethod
    def _response_to_frame(response: EngineOHLCVResponse) -> pd.DataFrame:
        """Convert an engine response to the canonical csm OHLCV DataFrame.

        Decimal-as-string wire values (already parsed to ``Decimal`` by the
        client) are cast to ``float`` to match the existing internal contract.
        ``ts`` (UTC bar-open) is converted to ``Asia/Bangkok``.
        """
        empty_index: pd.DatetimeIndex = pd.DatetimeIndex([], tz=TIMEZONE, name="datetime")
        if not response.bars:
            return pd.DataFrame(columns=_OHLCV_COLUMNS, index=empty_index)

        records: list[dict[str, float]] = [
            {
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }
            for bar in response.bars
        ]
        raw_index: pd.DatetimeIndex = pd.DatetimeIndex([bar.ts for bar in response.bars])
        if raw_index.tz is None:
            raw_index = raw_index.tz_localize("UTC")
        index: pd.DatetimeIndex = raw_index.tz_convert(TIMEZONE)
        index.name = "datetime"
        frame: pd.DataFrame = pd.DataFrame.from_records(records, index=index)
        return frame[_OHLCV_COLUMNS].sort_index()

    async def fetch(
        self,
        symbol: str,
        interval: str,
        bars: int,
        adjustment: str | None = None,
    ) -> pd.DataFrame:
        """Read historical OHLCV for a single symbol from the Market Data Engine.

        Args:
            symbol: Instrument symbol (e.g. ``"SET:AOT"``).
            interval: tvkit-style interval string (e.g. ``"1D"``); mapped to the
                engine timeframe (``"1d"``/``"1h"``/``"5m"``).
            bars: Maximum number of bars to request (sent as the engine ``limit``).
            adjustment: ``"splits"`` or ``"dividends"``. When ``None``, falls back
                to ``settings.tvkit_adjustment``. ``"dividends"`` reads the
                adjust-on-read endpoint; ``"splits"`` reads raw bars.

        Returns:
            DataFrame in the canonical csm OHLCV shape (see module docstring).

        Raises:
            DataAccessError: If ``settings.public_mode`` is ``True``.
            ValueError: If ``interval`` or ``adjustment`` is unsupported.
            EngineReadError: If the engine read fails.
        """
        if self._settings.public_mode:
            raise DataAccessError(
                "Data fetching is disabled in public mode. "
                "Set CSM_PUBLIC_MODE=false to read from the Market Data Engine."
            )
        timeframe, adjusted = self._resolve(interval, adjustment, self._settings.tvkit_adjustment)
        async with self._build_client() as client:
            response = await self._get_one(client, symbol, timeframe, adjusted, bars)
        return self._response_to_frame(response)

    async def fetch_batch(
        self,
        symbols: list[str],
        interval: str,
        bars: int,
        adjustment: str | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Read OHLCV for multiple symbols concurrently from the engine.

        Concurrency is bounded by ``settings.tvkit_concurrency``. Per-symbol
        failures are logged and the symbol is omitted from the result; the batch
        continues for all others — matching ``OHLCVLoader.fetch_batch``.

        Args:
            symbols: Instrument symbols to request.
            interval: tvkit-style interval string (e.g. ``"1D"``).
            bars: Maximum bars per symbol (engine ``limit``).
            adjustment: ``"splits"`` or ``"dividends"``; ``None`` falls back to
                ``settings.tvkit_adjustment``.

        Returns:
            Mapping from symbol to OHLCV DataFrame. Failed symbols are omitted.

        Raises:
            DataAccessError: If ``settings.public_mode`` is ``True``.
            ValueError: If ``interval`` or ``adjustment`` is unsupported.
        """
        if self._settings.public_mode:
            raise DataAccessError(
                "Data fetching is disabled in public mode. "
                "Set CSM_PUBLIC_MODE=false to read from the Market Data Engine."
            )
        timeframe, adjusted = self._resolve(interval, adjustment, self._settings.tvkit_adjustment)

        async with self._build_client() as client:

            async def _fetch_symbol(target_symbol: str) -> tuple[str, pd.DataFrame | None]:
                async with self._semaphore:
                    try:
                        response = await self._get_one(
                            client, target_symbol, timeframe, adjusted, bars
                        )
                    except MarketDataEngineError as exc:
                        logger.warning(
                            "Failed to read symbol from engine",
                            extra={"symbol": target_symbol, "error": str(exc)},
                        )
                        return target_symbol, None
                    logger.info("Read symbol from engine", extra={"symbol": target_symbol})
                    return target_symbol, self._response_to_frame(response)

            tasks: list[asyncio.Task[tuple[str, pd.DataFrame | None]]] = [
                asyncio.create_task(_fetch_symbol(symbol)) for symbol in symbols
            ]
            results: list[tuple[str, pd.DataFrame | None]] = await asyncio.gather(*tasks)

        return {symbol: frame for symbol, frame in results if frame is not None}

    @staticmethod
    async def _get_one(
        client: MarketDataEngineClient,
        symbol: str,
        timeframe: str,
        adjusted: bool,
        bars: int,
    ) -> EngineOHLCVResponse:
        return await client.get_ohlcv(symbol, timeframe, adjusted=adjusted, limit=bars)


__all__: list[str] = ["MarketDataEngineLoader"]
