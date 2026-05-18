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

# Standard crontab numbering: 0=Sun, 1=Mon, …, 6=Sat (and 7 = Sun).
# APScheduler's CronTrigger numeric numbering is 0=Mon, …, 6=Sun — so passing a
# raw crontab field through ``from_crontab`` silently shifts every weekday by one.
# We translate numeric tokens to APScheduler's name form (``mon`` … ``sun``)
# before constructing the trigger.
_STANDARD_DOW_NAMES: tuple[str, ...] = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


def _convert_dow_token(tok: str) -> str:
    """Map a single crontab day-of-week token (digit or name) to a day name."""

    tok = tok.strip().lower()
    if tok.isdigit():
        return _STANDARD_DOW_NAMES[int(tok) % 7]
    return tok


def _convert_dow_atom(atom: str) -> str:
    """Convert one comma-separated atom — possibly a range or step expression."""

    if atom in ("*", "?"):
        return atom
    step = ""
    base = atom
    if "/" in atom:
        base, step_val = atom.split("/", 1)
        step = f"/{step_val}"
    if "-" in base:
        lo, hi = base.split("-", 1)
        return f"{_convert_dow_token(lo)}-{_convert_dow_token(hi)}{step}"
    return f"{_convert_dow_token(base)}{step}"


def _standard_dow_to_apscheduler(field: str) -> str:
    """Translate a standard-crontab day_of_week field to APScheduler form."""

    return ",".join(_convert_dow_atom(a) for a in field.split(","))


def _trigger_from_standard_crontab(expr: str, timezone: str) -> CronTrigger:
    """Parse a 5-field standard crontab into a :class:`CronTrigger`.

    Equivalent to :meth:`CronTrigger.from_crontab` but correctly maps the
    day_of_week numbering. See module-level comment for the rationale.
    """

    fields = expr.split()
    if len(fields) != 5:
        msg = f"Expected 5-field crontab expression, got {len(fields)}: {expr!r}"
        raise ValueError(msg)
    minute, hour, day, month, dow = fields
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=_standard_dow_to_apscheduler(dow),
        timezone=timezone,
    )


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
        trigger=_trigger_from_standard_crontab(
            settings.refresh_cron, timezone="Asia/Bangkok"
        ),
        id="daily_refresh",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )
    return scheduler
