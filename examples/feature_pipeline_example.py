"""Example: compute a feature panel from synthetic OHLCV data."""

import asyncio
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from csm.config.settings import settings
from csm.data.store import ParquetStore
from csm.features.pipeline import FeaturePipeline

logger: logging.Logger = logging.getLogger(__name__)


async def main() -> None:
    """Build a synthetic feature panel and persist it to a temporary store."""

    logging.basicConfig(level=settings.log_level)
    if settings.public_mode:
        logger.warning("Public mode is enabled. This example uses synthetic in-memory data only.")

    dates: pd.DatetimeIndex = pd.date_range("2022-01-03", periods=400, freq="B", tz="Asia/Bangkok")
    price_map: dict[str, pd.DataFrame] = {}
    for offset, symbol in enumerate(["SET:AOT", "SET:CPALL", "SET:PTT", "SET:ADVANC"]):
        close: pd.Series = pd.Series(100.0 + np.cumsum(np.full(len(dates), 0.1 + offset * 0.01)), index=dates)
        price_map[symbol] = pd.DataFrame(
            {
                "open": close.shift(1).fillna(close.iloc[0]),
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": pd.Series(3_000_000.0, index=dates),
            }
        )
    store: ParquetStore = ParquetStore(Path("./data/processed_examples"))
    panel: pd.DataFrame = FeaturePipeline(store=store).build(
        prices=price_map,
        rebalance_dates=list(pd.date_range("2023-01-31", periods=4, freq="ME", tz="Asia/Bangkok")),
    )
    logger.info("Feature pipeline example rows", extra={"rows": len(panel.index)})


if __name__ == "__main__":
    asyncio.run(main())