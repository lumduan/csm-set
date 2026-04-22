"""Async OHLCV loading utilities backed by tvkit."""

import asyncio
import logging

import pandas as pd
from tvkit.api.chart import OHLCV
from tvkit.api.chart.models.ohlcv import OHLCVBar

from csm.config.constants import TIMEZONE
from csm.config.settings import Settings
from csm.data.exceptions import DataAccessError, FetchError

logger: logging.Logger = logging.getLogger(__name__)


class OHLCVLoader:
    """Fetch OHLCV data asynchronously via tvkit.

    Args:
        settings: Application settings controlling runtime mode and credentials.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings: Settings = settings

    async def fetch(self, symbol: str, interval: str, bars: int) -> pd.DataFrame:
        """Fetch historical OHLCV data for a single symbol.

        Args:
            symbol: TradingView symbol identifier.
            interval: TradingView interval string.
            bars: Number of bars to request.

        Returns:
            DataFrame indexed by timezone-aware timestamps with OHLCV columns.

        Raises:
            DataAccessError: If public mode is enabled.
            FetchError: If tvkit raises an error or returns malformed data.
        """

        if self._settings.public_mode:
            raise DataAccessError(
                "Data fetching is disabled in public mode. "
                "Raw market data is not distributed with this repository. "
                "Set CSM_PUBLIC_MODE=false and provide tvkit credentials to enable."
            )

        try:
            async with OHLCV() as client:
                bars_data: list[OHLCVBar] = await client.get_historical_ohlcv(
                    symbol,
                    interval=interval,
                    bars_count=bars,
                )

            records: list[dict[str, float | str | int]] = []
            for bar in bars_data:
                record: dict[str, float | str | int] = {
                    "timestamp": getattr(bar, "timestamp"),
                    "open": float(getattr(bar, "open")),
                    "high": float(getattr(bar, "high")),
                    "low": float(getattr(bar, "low")),
                    "close": float(getattr(bar, "close")),
                    "volume": float(getattr(bar, "volume")),
                }
                records.append(record)

            frame: pd.DataFrame = pd.DataFrame.from_records(records)
            if frame.empty:
                return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

            index: pd.DatetimeIndex = pd.to_datetime(frame.pop("timestamp"), utc=True)
            frame.index = index.tz_convert(TIMEZONE)
            frame = frame[["open", "high", "low", "close", "volume"]].sort_index()
            return frame
        except Exception as exc:  # noqa: BLE001
            raise FetchError(f"Failed to fetch OHLCV for {symbol}: {exc}") from exc

    async def fetch_batch(
        self,
        symbols: list[str],
        interval: str,
        bars: int,
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for multiple symbols concurrently.

        Args:
            symbols: TradingView symbols to request.
            interval: TradingView interval string.
            bars: Number of bars per symbol.

        Returns:
            Mapping from symbol to OHLCV DataFrame. Failed symbols are omitted.

        Raises:
            DataAccessError: If public mode is enabled.
        """

        if self._settings.public_mode:
            raise DataAccessError(
                "Data fetching is disabled in public mode. "
                "Raw market data is not distributed with this repository. "
                "Set CSM_PUBLIC_MODE=false and provide tvkit credentials to enable."
            )

        async def _fetch_symbol(target_symbol: str) -> tuple[str, pd.DataFrame | None]:
            try:
                frame: pd.DataFrame = await self.fetch(target_symbol, interval, bars)
                logger.info("Fetched symbol successfully", extra={"symbol": target_symbol})
                return target_symbol, frame
            except FetchError as exc:
                logger.warning(
                    "Failed to fetch symbol",
                    extra={"symbol": target_symbol, "error": str(exc)},
                )
                return target_symbol, None

        tasks: list[asyncio.Task[tuple[str, pd.DataFrame | None]]] = [
            asyncio.create_task(_fetch_symbol(symbol)) for symbol in symbols
        ]
        results: list[tuple[str, pd.DataFrame | None]] = await asyncio.gather(*tasks)
        return {symbol: frame for symbol, frame in results if frame is not None}


__all__: list[str] = ["OHLCVLoader"]