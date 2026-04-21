"""Build tradable universe snapshots from raw parquet data."""

import asyncio
import logging
from pathlib import Path

import pandas as pd

from csm.config.settings import settings
from csm.data.store import ParquetStore
from csm.data.universe import UniverseBuilder

logger: logging.Logger = logging.getLogger(__name__)


async def main() -> None:
    """Build and persist the current tradable universe."""

    logging.basicConfig(level=settings.log_level)
    if settings.public_mode:
        raise RuntimeError("build_universe.py is owner-only. Set CSM_PUBLIC_MODE=false before running.")

    raw_store: ParquetStore = ParquetStore(Path(settings.data_dir) / "raw")
    processed_store: ParquetStore = ParquetStore(Path(settings.data_dir) / "processed")
    price_data: dict[str, pd.DataFrame] = {
        key.replace("_", ":", 1): raw_store.load(key) for key in raw_store.list_keys()
    }
    as_of: pd.Timestamp = pd.Timestamp.now(tz="Asia/Bangkok")
    symbols: list[str] = UniverseBuilder().build(price_data=price_data, as_of=as_of)
    universe_frame: pd.DataFrame = pd.DataFrame({"symbol": symbols})
    processed_store.save("universe_latest", universe_frame)
    logger.info("Saved universe snapshot", extra={"count": len(symbols)})
    await asyncio.sleep(0)


if __name__ == "__main__":
    asyncio.run(main())