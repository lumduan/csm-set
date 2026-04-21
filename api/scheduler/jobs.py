"""Owner-side APScheduler jobs for csm-set."""

import asyncio
import logging
import time

import pandas as pd
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from csm.config.settings import Settings
from csm.data.loader import OHLCVLoader
from csm.data.store import ParquetStore
from csm.features.pipeline import FeaturePipeline

logger: logging.Logger = logging.getLogger(__name__)


async def daily_refresh(settings: Settings, store: ParquetStore) -> None:
    """Refresh OHLCV data and rebuild the latest feature panel."""

    started_at: float = time.perf_counter()
    universe: pd.DataFrame = store.load("universe_latest")
    symbols: list[str] = universe["symbol"].astype(str).tolist() if "symbol" in universe.columns else []
    loader: OHLCVLoader = OHLCVLoader(settings=settings)
    fetched: dict[str, pd.DataFrame] = await loader.fetch_batch(symbols=symbols, interval="1D", bars=600)
    store.save("prices_latest", pd.concat({symbol: frame["close"] for symbol, frame in fetched.items()}, axis=1))
    rebalance_dates: list[pd.Timestamp] = list(
        pd.date_range(end=pd.Timestamp.now(tz="Asia/Bangkok"), periods=12, freq="BME")
    )
    FeaturePipeline(store=store).build(prices=fetched, rebalance_dates=rebalance_dates)
    duration: float = time.perf_counter() - started_at
    logger.info(
        "Completed daily refresh",
        extra={"duration_seconds": duration, "symbol_count": len(symbols), "failures": len(symbols) - len(fetched)},
    )


def create_scheduler(settings: Settings, store: ParquetStore) -> AsyncIOScheduler | None:
    """Create and configure the owner-side scheduler when private mode is enabled."""

    if settings.public_mode:
        return None
    scheduler: AsyncIOScheduler = AsyncIOScheduler(timezone="Asia/Bangkok")

    async def _job_wrapper() -> None:
        await daily_refresh(settings=settings, store=store)

    scheduler.add_job(_job_wrapper, trigger="cron", id="daily_refresh", replace_existing=True)
    return scheduler
