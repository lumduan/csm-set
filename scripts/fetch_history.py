"""Bulk fetch SET OHLCV history via tvkit and save to parquet.

Usage (owner only - requires tvkit credentials in .env):
    uv run python scripts/fetch_history.py

Idempotent: skips symbols already present in data/raw/.
"""

import asyncio
import logging
from pathlib import Path

from csm.config.settings import settings
from csm.data.loader import OHLCVLoader
from csm.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)


async def main() -> None:
    """Fetch historical OHLCV data for a starter SET symbol universe."""

    logging.basicConfig(level=settings.log_level)
    if settings.public_mode:
        raise RuntimeError(
            "fetch_history.py is owner-only. Set CSM_PUBLIC_MODE=false before running."
        )

    symbols: list[str] = ["SET:AOT", "SET:CPALL", "SET:PTT", "SET:ADVANC", "SET:KBANK"]
    store: ParquetStore = ParquetStore(Path(settings.data_dir) / "raw")
    loader: OHLCVLoader = OHLCVLoader(settings=settings)
    pending_symbols: list[str] = [
        symbol for symbol in symbols if not store.exists(symbol.replace(":", "_"))
    ]
    fetched = await loader.fetch_batch(symbols=pending_symbols, interval="1D", bars=3000)
    for symbol, frame in fetched.items():
        store.save(symbol.replace(":", "_"), frame)
    logger.info("Fetched history", extra={"requested": len(pending_symbols), "saved": len(fetched)})


if __name__ == "__main__":
    asyncio.run(main())
