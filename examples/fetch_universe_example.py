"""Example: build a universe from synthetic OHLCV inputs."""

import asyncio
import logging

import numpy as np
import pandas as pd

from csm.config.settings import settings
from csm.data.universe import UniverseBuilder

logger: logging.Logger = logging.getLogger(__name__)


async def main() -> None:
    """Build a simple universe snapshot from synthetic data."""

    logging.basicConfig(level=settings.log_level)
    if settings.public_mode:
        logger.warning("Public mode is enabled. This example uses only synthetic in-memory data.")

    index: pd.DatetimeIndex = pd.date_range("2024-01-01", periods=260, freq="B", tz="Asia/Bangkok")
    price_data: dict[str, pd.DataFrame] = {}
    for symbol in ["SET:AOT", "SET:CPALL", "SET:PTT"]:
        close: pd.Series = pd.Series(50.0 + np.linspace(0.0, 10.0, len(index)), index=index)
        price_data[symbol] = pd.DataFrame(
            {
                "open": close.shift(1).fillna(close.iloc[0]),
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": pd.Series(2_500_000.0, index=index),
            }
        )
    universe: list[str] = UniverseBuilder().build(price_data, as_of=index[-1])
    logger.info("Universe example output", extra={"symbols": universe})


if __name__ == "__main__":
    asyncio.run(main())
