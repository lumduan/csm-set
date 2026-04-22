"""Async OHLCV loading utilities backed by tvkit.

Public mode guard:
    When ``Settings.public_mode`` is ``True``, every call to ``fetch`` or
    ``fetch_batch`` raises ``DataAccessError`` immediately — no network call is
    made.  This is the only safe mode when tvkit credentials are unavailable
    (e.g. the public-facing Docker image).

Retry contract:
    ``fetch`` retries transient infrastructure failures up to
    ``Settings.tvkit_retry_attempts`` additional times (total attempts =
    ``tvkit_retry_attempts + 1``).  Non-transient failures (bad credentials,
    unknown symbol, bad request parameters) are raised immediately without
    retry.
"""

import asyncio
import logging

import pandas as pd
from tvkit.api.chart import OHLCV
from tvkit.api.chart.exceptions import StreamConnectionError
from tvkit.api.chart.models.ohlcv import OHLCVBar

from csm.config.constants import TIMEZONE
from csm.config.settings import Settings
from csm.data.exceptions import DataAccessError, FetchError

logger: logging.Logger = logging.getLogger(__name__)

_TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    asyncio.TimeoutError,
    OSError,
    EOFError,
    StreamConnectionError,
)


class OHLCVLoader:
    """Fetch OHLCV data asynchronously via tvkit.

    Args:
        settings: Application settings controlling runtime mode and concurrency.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings: Settings = settings
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(settings.tvkit_concurrency)

    async def fetch(self, symbol: str, interval: str, bars: int) -> pd.DataFrame:
        """Fetch historical OHLCV data for a single symbol.

        Retries up to ``settings.tvkit_retry_attempts`` times on transient
        network / WebSocket failures.  Non-transient failures (auth errors, bad
        symbol, malformed response) are raised immediately without retry.

        Args:
            symbol: TradingView symbol identifier (e.g. ``"SET:AOT"``).
            interval: TradingView interval string (e.g. ``"1D"``).
            bars: Number of bars to request.

        Returns:
            DataFrame with columns ``["open", "high", "low", "close", "volume"]``,
            indexed by a ``DatetimeIndex`` (timezone ``Asia/Bangkok``, name
            ``"datetime"``), sorted ascending.  Returns a zero-row DataFrame
            with the same index schema when tvkit returns no bars.

        Raises:
            DataAccessError: If ``settings.public_mode`` is ``True``.
            FetchError: If all retry attempts fail or a non-transient error occurs.
        """
        if self._settings.public_mode:
            raise DataAccessError(
                "Data fetching is disabled in public mode. "
                "Raw market data is not distributed with this repository. "
                "Set CSM_PUBLIC_MODE=false and provide tvkit credentials to enable."
            )

        bars_data: list[OHLCVBar] = []
        for attempt in range(self._settings.tvkit_retry_attempts + 1):
            try:
                async with OHLCV() as client:
                    bars_data = await client.get_historical_ohlcv(
                        symbol,
                        interval=interval,
                        bars_count=bars,
                    )
                break
            except _TRANSIENT_EXCEPTIONS as exc:
                if attempt == self._settings.tvkit_retry_attempts:
                    raise FetchError(
                        f"Failed to fetch OHLCV for {symbol}: all retries exhausted "
                        f"({self._settings.tvkit_retry_attempts + 1} attempts): {exc}"
                    ) from exc
                logger.warning(
                    "Transient error fetching %s (attempt %d/%d): %s",
                    symbol,
                    attempt + 1,
                    self._settings.tvkit_retry_attempts + 1,
                    exc,
                )
                continue
            except Exception as exc:
                raise FetchError(f"Failed to fetch OHLCV for {symbol}: {exc}") from exc

        empty_index: pd.DatetimeIndex = pd.DatetimeIndex([], tz=TIMEZONE, name="datetime")
        if not bars_data:
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume"],
                index=empty_index,
            )

        records: list[dict[str, float | str | int]] = []
        for bar in bars_data:
            record: dict[str, float | str | int] = {
                "timestamp": bar.timestamp,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }
            records.append(record)

        frame: pd.DataFrame = pd.DataFrame.from_records(records)
        raw_index = pd.to_datetime(frame.pop("timestamp"), utc=True)
        index: pd.DatetimeIndex = pd.DatetimeIndex(raw_index).tz_convert(TIMEZONE)
        index.name = "datetime"
        frame.index = index
        frame = frame[["open", "high", "low", "close", "volume"]].sort_index()
        return frame

    async def fetch_batch(
        self,
        symbols: list[str],
        interval: str,
        bars: int,
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for multiple symbols concurrently.

        Concurrent fetches are bounded by ``settings.tvkit_concurrency`` via
        an internal semaphore.  Per-symbol failures are logged and the symbol
        is omitted from the result; the batch continues for all other symbols.

        Result dict entries appear in the same order as the input ``symbols``
        list (minus any failed symbols), because ``asyncio.gather`` preserves
        task order.

        Args:
            symbols: TradingView symbols to request.
            interval: TradingView interval string (e.g. ``"1D"``).
            bars: Number of bars per symbol.

        Returns:
            Mapping from symbol to OHLCV DataFrame.  Failed symbols are omitted.

        Raises:
            DataAccessError: If ``settings.public_mode`` is ``True``.
        """
        if self._settings.public_mode:
            raise DataAccessError(
                "Data fetching is disabled in public mode. "
                "Raw market data is not distributed with this repository. "
                "Set CSM_PUBLIC_MODE=false and provide tvkit credentials to enable."
            )

        async def _fetch_symbol(target_symbol: str) -> tuple[str, pd.DataFrame | None]:
            async with self._semaphore:
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
