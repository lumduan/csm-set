"""Example: run a synthetic momentum backtest."""

import asyncio
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from csm.config.settings import settings
from csm.data.store import ParquetStore
from csm.features.pipeline import FeaturePipeline
from csm.research.backtest import BacktestConfig, MomentumBacktest

logger: logging.Logger = logging.getLogger(__name__)


async def main() -> None:
    """Run a full synthetic feature-to-backtest workflow."""

    logging.basicConfig(level=settings.log_level)
    if settings.public_mode:
        logger.warning(
            "Public mode is enabled. This example uses synthetic prices and does not fetch data."
        )

    dates: pd.DatetimeIndex = pd.date_range("2022-01-03", periods=500, freq="B", tz="Asia/Bangkok")
    symbols: list[str] = ["SET:AOT", "SET:CPALL", "SET:PTT", "SET:ADVANC", "SET:KBANK"]
    price_map: dict[str, pd.DataFrame] = {}
    close_matrix: pd.DataFrame = pd.DataFrame(index=dates)
    for offset, symbol in enumerate(symbols):
        close: pd.Series = pd.Series(
            100.0 * np.exp(np.linspace(0.0, 0.5 + offset * 0.05, len(dates))), index=dates
        )
        close_matrix[symbol] = close
        price_map[symbol] = pd.DataFrame(
            {
                "open": close.shift(1).fillna(close.iloc[0]),
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": pd.Series(4_000_000.0, index=dates),
            }
        )
    store: ParquetStore = ParquetStore(Path("./data/processed_examples"))
    pipeline: FeaturePipeline = FeaturePipeline(store=store)
    feature_panel: pd.DataFrame = pipeline.build(
        prices=price_map,
        rebalance_dates=list(pd.date_range("2023-01-31", periods=8, freq="ME", tz="Asia/Bangkok")),
    )
    volume_matrix: pd.DataFrame = pipeline.build_volume_matrix()
    result = MomentumBacktest(store=store).run(
        feature_panel, close_matrix, BacktestConfig(), volumes=volume_matrix
    )
    logger.info("Backtest example metrics", extra=result.metrics)


if __name__ == "__main__":
    asyncio.run(main())
