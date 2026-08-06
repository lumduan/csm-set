"""Owner-side APScheduler jobs for csm-set."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import pandas as pd
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from csm.config.constants import INDEX_SYMBOL, TIMEZONE
from csm.config.settings import Settings
from csm.data.calendar import is_set_holiday
from csm.data.sources import OHLCVSource, build_ohlcv_loader
from csm.data.store import ParquetStore
from csm.features.pipeline import FeaturePipeline
from csm.live.portfolio import load_live_portfolio

if TYPE_CHECKING:
    from csm.adapters import AdapterManager

logger: logging.Logger = logging.getLogger(__name__)

# Standard crontab numbering: 0=Sun, 1=Mon, …, 6=Sat (and 7 = Sun).
# APScheduler's CronTrigger numeric numbering is 0=Mon, …, 6=Sun — so passing a
# raw crontab field through ``from_crontab`` silently shifts every weekday by one.
# We translate numeric tokens to APScheduler's name form (``mon`` … ``sun``)
# before constructing the trigger.
_STANDARD_DOW_NAMES: tuple[str, ...] = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")

# Default location of the live-portfolio config consumed by the held-symbol
# priority phase of ``daily_refresh``. Mirrors the default in
# ``csm.adapters.hooks.DEFAULT_LIVE_PORTFOLIO_PATH``.
DEFAULT_LIVE_PORTFOLIO_PATH: Path = Path("configs/live_portfolio.yaml")

# Module-local alias for ``asyncio.sleep`` so tests can patch this attribute
# without affecting pytest-asyncio's own event-loop machinery.
_sleep = asyncio.sleep


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


def _write_marker(settings: Settings, summary: dict[str, Any]) -> dict[str, Any]:
    """Persist *summary* to ``results/.tmp/last_refresh.json`` and return it.

    Written atomically (tmp file + rename) so a reader never sees a half-written
    marker. Shared by both exits from :func:`daily_refresh` — the normal one and
    the holiday skip — so a skipped run is still *observable*: it reports that
    the job fired and why it did nothing, rather than leaving yesterday's marker
    in place and looking like the scheduler never ran.

    Args:
        settings: Provides ``results_dir``.
        summary: The run summary. ``timestamp`` is added here.

    Returns:
        The summary as written, including ``timestamp``.
    """
    marker: dict[str, Any] = {"timestamp": datetime.now(UTC).isoformat(), **summary}
    marker_dir = settings.results_dir / ".tmp"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker_path = marker_dir / "last_refresh.json"
    tmp_marker = marker_path.with_suffix(".tmp")
    tmp_marker.write_text(json.dumps(marker, indent=2), encoding="utf-8")
    tmp_marker.rename(marker_path)
    return marker


def _has_usable_data(frame: pd.DataFrame | None) -> bool:
    """Return ``True`` when ``frame`` carries at least one real close price.

    ``fetch_batch`` omits hard failures from its result, so a key being present
    normally means success. It does not *guarantee* it: a frame can arrive
    structurally valid and carry no data — an empty index, or a ``close`` column
    that is entirely NaN. Treating that as a successful fetch is the
    false-liveness defect this guards; the retry loop and the ``failures`` count
    both key off the answer.
    """
    if frame is None or frame.empty or "close" not in frame.columns:
        return False
    return bool(frame["close"].notna().any())


async def _fetch_batch_with_retry(
    loader: OHLCVSource,
    symbols: list[str],
    *,
    max_attempts: int,
    base_delay_secs: int,
    interval: str = "1D",
    bars: int = 600,
    phase_label: str = "fetch",
) -> tuple[dict[str, pd.DataFrame], int]:
    """Fetch ``symbols`` via ``loader.fetch_batch``, retrying the failed subset.

    The TradingView WebSocket occasionally closes a large fraction of a burst
    fetch with an identical 1000-OK pattern (an upstream rate-limit /
    connection-recycle). ``OHLCVLoader.fetch`` already retries per symbol on
    transient errors, but those retries fire inside the same burst and tend to
    die together. This outer loop waits between attempts so the connection
    pool can recover before re-fetching only the still-missing symbols.

    Returns a ``(merged_fetched, retries_used)`` pair. ``retries_used`` is the
    number of *retries* fired (0 on the happy path), not the total attempts —
    the caller sums it across phases for the marker file.
    """

    merged: dict[str, pd.DataFrame] = {}
    remaining: list[str] = list(symbols)
    retries_used: int = 0

    if not remaining or max_attempts < 1:
        return merged, 0

    for attempt_idx in range(max_attempts):
        attempt_no: int = attempt_idx + 1
        if attempt_idx > 0:
            # Exponential backoff with ±20% jitter so simultaneous phases or
            # retries do not re-collide on the upstream.
            delay: float = base_delay_secs * (2 ** (attempt_idx - 1))
            jitter: float = delay * random.uniform(-0.2, 0.2)  # noqa: S311
            wait: float = max(0.0, delay + jitter)
            logger.warning(
                "%s: %d symbol(s) still missing after attempt %d/%d; sleeping %.1fs before retry",
                phase_label,
                len(remaining),
                attempt_idx,
                max_attempts,
                wait,
            )
            await _sleep(wait)
            retries_used += 1

        result: dict[str, pd.DataFrame] = await loader.fetch_batch(
            symbols=remaining, interval=interval, bars=bars
        )
        # A symbol counts as recovered only when it came back with USABLE data.
        # Testing `s in result` tests key presence, which a structurally valid but
        # empty/all-NaN frame also satisfies — so a symbol that returned nothing
        # dropped out of `remaining`, was never retried, and was reported as a
        # success. That false liveness is how SET:BANPU read as healthy from
        # 2026-07-17 until a month-end audit caught it.
        recovered: list[str] = [s for s in remaining if _has_usable_data(result.get(s))]
        # Merge only the usable frames. An unusable one must not reach the caller
        # either: it would land in prices_latest as an all-NaN column and count
        # toward `symbols_fetched`, making the marker file overstate the run.
        merged.update({s: result[s] for s in recovered})
        remaining = [s for s in remaining if s not in recovered]
        logger.info(
            "%s attempt %d/%d: requested=%d recovered=%d still_failing=%d",
            phase_label,
            attempt_no,
            max_attempts,
            len(recovered) + len(remaining),
            len(recovered),
            len(remaining),
        )
        if not remaining:
            break

    if remaining:
        logger.warning(
            "%s: exhausted %d attempts with %d symbol(s) still missing: %s",
            phase_label,
            max_attempts,
            len(remaining),
            remaining,
        )

    return merged, retries_used


def _held_symbols_from_config(path: Path) -> list[str]:
    """Return the sorted, qualified-symbol list of held positions, or empty.

    Uses ``LivePosition.qualified_symbol`` so each name carries the ``SET:``
    prefix — the same form used by ``universe_latest.parquet`` and required by
    the tvkit loader. Stripping the prefix here causes tvkit to fail every
    held fetch and the merged ``fetched`` dict to use keys that downstream
    NAV-reconstruction lookups can't find.

    Tolerates a missing or malformed config file by logging and returning an
    empty list — the held-priority phase is best-effort.
    """

    try:
        config = load_live_portfolio(path)
    except (ValueError, OSError):
        logger.warning(
            "daily_refresh: failed to load live_portfolio config from %s; "
            "skipping held-symbol priority phase",
            path,
            exc_info=True,
        )
        return []
    if config is None:
        return []
    return sorted({pos.qualified_symbol for pos in config.positions})


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

    # Phase 0 — is the market even open today?
    #
    # Purely an optimisation, and deliberately a weak one. On a published SET
    # closure the scheduler still fires (it holds no calendar of its own), spends
    # ~6 minutes fetching a couple of hundred symbols that cannot have moved, and
    # is then correctly refused by the no-fresh-bar guard at the write. This skips
    # the wasted fetch and records why.
    #
    # `is_set_holiday` resolves live calendar -> committed fallback table -> open.
    # It fails open ONLY when neither source covers the year, so a settfex outage
    # cannot suppress a real session's refresh while a *known* closure is still
    # caught with the endpoint down — which since 2026-08-04 is the normal state.
    # The no-bar guard downstream remains the ground truth for whether anything is
    # written, and it also covers what no calendar can: the market traded but our
    # fetch came back empty.
    today_bkk: date = datetime.now(tz=ZoneInfo(TIMEZONE)).date()
    holiday, holiday_name = await is_set_holiday(today_bkk)
    if holiday:
        logger.info(
            "daily refresh: %s is a SET holiday (%s) — skipping the fetch entirely",
            today_bkk.isoformat(),
            holiday_name,
        )
        return _write_marker(
            settings,
            {
                "symbols_fetched": 0,
                "failures": 0,
                "duration_seconds": round(time.perf_counter() - started_at, 3),
                "held_symbols_fetched": 0,
                "held_symbols_failed": 0,
                "retry_attempts_used": 0,
                "index_fetched": False,
                "skipped_reason": "set_holiday",
                "skipped_detail": holiday_name,
            },
        )

    universe: pd.DataFrame = store.load("universe_latest")
    symbols: list[str] = (
        universe["symbol"].astype(str).tolist() if "symbol" in universe.columns else []
    )
    # Always fetch the SET index alongside the universe. `FeaturePipeline.build`
    # gates the risk-adjusted factors on exactly this key being present in
    # `prices` (`pipeline.py`: `if _INDEX_SYMBOL in prices`), so without it
    # `residual_momentum` and `sharpe_momentum` are silently never computed —
    # and `residual_momentum` is the only factor that cleared the historical
    # ICIR > 0.15 gate. Its absence forced a manual re-fetch at three
    # consecutive month-ends before this was found. `scripts/fetch_history.py`
    # has always done this; the scheduled refresh simply never did.
    #
    # The index is a data input, not a universe member: the pipeline excludes it
    # from the feature loop and from the volume matrix, so it never ranks.
    if symbols and INDEX_SYMBOL not in symbols:
        symbols = [INDEX_SYMBOL, *symbols]
    loader: OHLCVSource = build_ohlcv_loader(settings)

    held_symbols: list[str] = _held_symbols_from_config(DEFAULT_LIVE_PORTFOLIO_PATH)
    held_set: set[str] = set(held_symbols)

    # Phase 1 — fetch held symbols first under a stricter retry policy so a
    # partial universe failure does not block NAV reconstruction / the
    # gateway POST in the post-refresh hook.
    held_prices: dict[str, pd.DataFrame]
    held_retries: int
    if held_symbols:
        held_prices, held_retries = await _fetch_batch_with_retry(
            loader,
            held_symbols,
            max_attempts=settings.refresh_held_max_attempts,
            base_delay_secs=settings.refresh_retry_delay_secs,
            phase_label="held-symbols",
        )
    else:
        held_prices, held_retries = {}, 0
    held_fetched_count: int = len(held_prices)
    held_failed_count: int = len(held_symbols) - held_fetched_count

    # Phase 2 — universe sweep, excluding the held names we just fetched.
    universe_only: list[str] = [s for s in symbols if s not in held_set]
    universe_prices, universe_retries = await _fetch_batch_with_retry(
        loader,
        universe_only,
        max_attempts=settings.refresh_universe_max_attempts,
        base_delay_secs=settings.refresh_retry_delay_secs,
        phase_label="universe",
    )

    # Held prices win on any overlap (they're the critical path).
    fetched: dict[str, pd.DataFrame] = {**universe_prices, **held_prices}
    retry_attempts_used: int = held_retries + universe_retries

    if fetched:
        store.save(
            "prices_latest",
            pd.concat({symbol: frame["close"] for symbol, frame in fetched.items()}, axis=1),
        )
    rebalance_dates: list[pd.Timestamp] = list(
        pd.date_range(end=pd.Timestamp.now(tz="Asia/Bangkok"), periods=12, freq="BME")
    )
    # `sector_rel_strength` is gated on a symbol → sector mapping the same way the
    # risk-adjusted factors are gated on the index. The universe snapshot is the
    # only place the refresh can get one, and it carried no sector column until
    # build_universe.py started emitting one — so the factor was never computed.
    # Absent column ⇒ None ⇒ the pipeline behaves exactly as before, which keeps
    # a refresh against an older snapshot working instead of erroring.
    symbol_sectors: dict[str, str] | None = None
    if "sector" in universe.columns:
        symbol_sectors = {
            str(sym): str(sec)
            for sym, sec in zip(universe["symbol"], universe["sector"], strict=True)
            if pd.notna(sec)
        }
    else:
        logger.warning(
            "daily refresh: universe_latest has no 'sector' column — sector_rel_strength "
            "will NOT be computed; rebuild the universe with scripts/build_universe.py"
        )
    FeaturePipeline(store=store).build(
        prices=fetched,
        rebalance_dates=rebalance_dates,
        symbol_sectors=symbol_sectors,
    )
    duration: float = time.perf_counter() - started_at
    # ``failures`` covers the union of held + universe so the legacy marker
    # field keeps the same meaning (requested - successfully fetched).
    failures: int = (len(held_symbols) + len(universe_only)) - len(fetched)
    # Surfaced on its own because its absence is silent and expensive: without the
    # index the pipeline computes 4 of 6 factors and says nothing, which is how
    # residual_momentum went missing for three months. `failures` alone would not
    # single it out among a couple of hundred symbols.
    index_fetched: bool = INDEX_SYMBOL in fetched
    if not index_fetched:
        logger.warning(
            "daily refresh: %s missing from the fetched set — residual_momentum and "
            "sharpe_momentum will NOT be computed for this panel",
            INDEX_SYMBOL,
        )
    logger.info(
        "Completed daily refresh",
        extra={
            "duration_seconds": duration,
            "symbol_count": len(held_symbols) + len(universe_only),
            "failures": failures,
            "held_symbols_fetched": held_fetched_count,
            "held_symbols_failed": held_failed_count,
            "retry_attempts_used": retry_attempts_used,
            "index_fetched": index_fetched,
        },
    )

    summary: dict[str, Any] = {
        "symbols_fetched": len(fetched),
        "failures": failures,
        "duration_seconds": round(duration, 3),
        "held_symbols_fetched": held_fetched_count,
        "held_symbols_failed": held_failed_count,
        "retry_attempts_used": retry_attempts_used,
        "index_fetched": index_fetched,
    }

    if adapters is not None:
        from csm.adapters.hooks import run_post_refresh_hook

        await run_post_refresh_hook(manager=adapters, store=store, summary=summary)

    return _write_marker(settings, summary)


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
        trigger=_trigger_from_standard_crontab(settings.refresh_cron, timezone="Asia/Bangkok"),
        id="daily_refresh",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )
    return scheduler
