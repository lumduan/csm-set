"""Owner-side APScheduler jobs for csm-set."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pandas as pd
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from csm.config.settings import Settings
from csm.data.loader import OHLCVLoader
from csm.data.store import ParquetStore
from csm.features.pipeline import FeaturePipeline

if TYPE_CHECKING:
    from csm.adapters import AdapterManager

logger: logging.Logger = logging.getLogger(__name__)


async def daily_refresh(
    settings: Settings,
    store: ParquetStore,
    adapters: AdapterManager | None = None,
) -> dict[str, Any]:
    """Refresh OHLCV data and rebuild the latest feature panel.

    Returns a summary dict stored on ``JobRecord.summary`` when submitted
    via :class:`JobRegistry`.
    """

    started_at: float = time.perf_counter()
    universe: pd.DataFrame = store.load("universe_latest")
    symbols: list[str] = (
        universe["symbol"].astype(str).tolist() if "symbol" in universe.columns else []
    )
    loader: OHLCVLoader = OHLCVLoader(settings=settings)
    fetched: dict[str, pd.DataFrame] = await loader.fetch_batch(
        symbols=symbols, interval="1D", bars=600
    )
    store.save(
        "prices_latest",
        pd.concat({symbol: frame["close"] for symbol, frame in fetched.items()}, axis=1),
    )
    rebalance_dates: list[pd.Timestamp] = list(
        pd.date_range(end=pd.Timestamp.now(tz="Asia/Bangkok"), periods=12, freq="BME")
    )
    FeaturePipeline(store=store).build(prices=fetched, rebalance_dates=rebalance_dates)
    duration: float = time.perf_counter() - started_at
    failures: int = len(symbols) - len(fetched)
    logger.info(
        "Completed daily refresh",
        extra={
            "duration_seconds": duration,
            "symbol_count": len(symbols),
            "failures": failures,
        },
    )

    summary: dict[str, Any] = {
        "symbols_fetched": len(fetched),
        "failures": failures,
        "duration_seconds": round(duration, 3),
    }

    if adapters is not None:
        from csm.adapters.hooks import run_post_refresh_hook

        await run_post_refresh_hook(manager=adapters, store=store, summary=summary)

    marker = {
        "timestamp": datetime.now(UTC).isoformat(),
        "symbols_fetched": len(fetched),
        "duration_seconds": round(duration, 3),
        "failures": failures,
    }
    marker_dir = settings.results_dir / ".tmp"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker_path = marker_dir / "last_refresh.json"
    tmp_marker = marker_path.with_suffix(".tmp")
    tmp_marker.write_text(json.dumps(marker, indent=2), encoding="utf-8")
    tmp_marker.rename(marker_path)

    return summary


def create_scheduler(
    settings: Settings,
    store: ParquetStore,
    adapters: AdapterManager | None = None,
) -> AsyncIOScheduler | None:
    """Create and configure the owner-side scheduler when private mode is enabled."""

    if settings.public_mode:
        return None
    scheduler: AsyncIOScheduler = AsyncIOScheduler(timezone="Asia/Bangkok")

    async def _job_wrapper() -> None:
        try:
            summary = await daily_refresh(settings=settings, store=store, adapters=adapters)
            logger.info("Scheduled daily_refresh completed", extra={"summary": summary})
        except Exception:
            logger.exception("Scheduled daily_refresh failed")

    scheduler.add_job(
        _job_wrapper,
        trigger=CronTrigger.from_crontab(settings.refresh_cron, timezone="Asia/Bangkok"),
        id="daily_refresh",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )
    return scheduler
