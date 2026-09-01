"""Live paper-trading portfolio state and NAV reconstruction.

Loads ``configs/live_portfolio.yaml`` and reprices the canonical positions
against ``prices_latest`` to derive the live portfolio NAV, daily return,
cumulative return, max drawdown, sharpe ratio, and daily PnL.

These metrics drive ``run_post_refresh_hook``'s writes to
``db_gateway.daily_performance`` and ``db_gateway.portfolio_snapshot`` so
both tables track the actual paper portfolio instead of the synthetic
equal-weight universe NAV that the ``equity_curve`` table carries.

The config file is the single source of truth; update it on each rebalance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from csm.research.strategy_report_models import StrategyReport

logger: logging.Logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR: int = 252
# Minimum daily-return sample before annualised Sharpe is meaningful.  With
# fewer observations the ratio swings wildly with each new bar (a single
# negative day on a 10-day window pulls Sharpe to ~−4); the live test only
# starts to produce a defensible Sharpe after ~6 trading weeks.
SHARPE_MIN_SAMPLE: int = 30


@dataclass(frozen=True)
class LivePosition:
    """A single held position keyed by SET symbol."""

    symbol: str
    shares: float
    avg_cost: float

    @property
    def qualified_symbol(self) -> str:
        """Return the symbol prefixed with ``SET:`` for parquet column lookup."""
        return self.symbol if ":" in self.symbol else f"SET:{self.symbol}"


@dataclass(frozen=True)
class LivePortfolioConfig:
    """Snapshot of the live paper-trading portfolio.

    Loaded from ``configs/live_portfolio.yaml``; mutated only on rebalance.
    """

    strategy_id: str
    entry_date: date
    starting_nav: float
    cash: float
    positions: tuple[LivePosition, ...]


@dataclass(frozen=True)
class LivePortfolioMetrics:
    """Computed live portfolio metrics for one trading day.

    ``report`` carries the optional :class:`StrategyReport` payload (Phase 1
    of feature-strategies-report-metrics). When present, it is embedded
    under ``extended_data.report`` in :meth:`as_dict` so it lands in the
    gateway ``daily_performance.metadata`` JSONB column verbatim.
    """

    snapshot_time: datetime
    total_value: float
    cash_balance: float
    daily_return: float
    cumulative_return: float
    max_drawdown: float
    sharpe_ratio: float
    daily_pnl: float
    positions_count: int
    report: StrategyReport | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a plain dict shaped for the gateway write methods.

        Existing scalar fields are preserved verbatim; the optional
        :class:`StrategyReport` (when present) is appended under
        ``extended_data.report``.
        """
        payload: dict[str, Any] = {
            "daily_return": self.daily_return,
            "cumulative_return": self.cumulative_return,
            "total_value": self.total_value,
            "cash_balance": self.cash_balance,
            "max_drawdown": self.max_drawdown,
            "sharpe_ratio": self.sharpe_ratio,
            "daily_pnl": round(self.daily_pnl, 2),
            "positions_count": self.positions_count,
        }
        if self.report is not None:
            payload["extended_data"] = {"report": self.report.model_dump(mode="json")}
        return payload


def load_live_portfolio(path: Path) -> LivePortfolioConfig | None:
    """Load the live-portfolio config file or return ``None`` when absent.

    Args:
        path: Path to the YAML config (``configs/live_portfolio.yaml``).

    Returns:
        Parsed config or ``None`` when the file does not exist.

    Raises:
        ValueError: When required fields are missing or malformed.
    """
    if not path.exists():
        logger.debug("live_portfolio config not found at %s", path)
        return None
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"live_portfolio config at {path} must be a YAML mapping, got {type(raw).__name__}"
        raise ValueError(msg)
    required: tuple[str, ...] = ("strategy_id", "entry_date", "starting_nav", "cash", "positions")
    missing: list[str] = [k for k in required if k not in raw]
    if missing:
        msg = f"live_portfolio config at {path} is missing required keys: {missing}"
        raise ValueError(msg)
    positions_raw: Any = raw["positions"]
    if not isinstance(positions_raw, list) or not positions_raw:
        msg = f"live_portfolio config at {path} must declare at least one position"
        raise ValueError(msg)
    positions: tuple[LivePosition, ...] = tuple(
        LivePosition(
            symbol=str(p["symbol"]),
            shares=float(p["shares"]),
            avg_cost=float(p["avg_cost"]),
        )
        for p in positions_raw
    )
    entry_raw: Any = raw["entry_date"]
    entry: date = entry_raw if isinstance(entry_raw, date) else date.fromisoformat(str(entry_raw))
    return LivePortfolioConfig(
        strategy_id=str(raw["strategy_id"]),
        entry_date=entry,
        starting_nav=float(raw["starting_nav"]),
        cash=float(raw["cash"]),
        positions=positions,
    )


def collapse_to_daily_bars(prices: pd.DataFrame) -> pd.DataFrame:
    """Collapse a price panel to exactly one row per trading day.

    The panel's contract is *one row per trading day*, and until 2026-09-01 that
    held for 948 consecutive bars without ever being asserted. On that date the
    vendor began emitting a **second** daily bar (a 10:00 BKK stamp beside the
    long-standing 09:55 one) covering a *subset* of symbols — 16 of 211 on
    2026-08-31, 41 of 211 on 2026-09-01 — so a single session arrived as two
    sparse, complementary rows.

    Anything reading the panel's last row then priced the book off whichever
    symbols happened to carry the later stamp. That is what wrote a NAV of
    373,561.70 against a true 1,273,881.70 (7 of 10 holdings unpriced, and
    silently worth zero — see :func:`drop_unpriced_days`), and what overwrote
    the banked 2026-08-31 ``equity_curve`` row with a two-symbol valuation.

    Within a day the bars are complementary and agree wherever they overlap, so
    the session is their union: ``GroupBy.last()`` takes the last **non-null**
    value per column, which is that union.

    The result is re-keyed to each day's **last original timestamp** rather than
    to local midnight. That is load-bearing: callers convert to UTC and then
    normalize, and a local-midnight key (00:00+07) converts to 17:00 UTC on the
    *previous* day, which would shift every date back by one. The real bar
    stamps (09:55/10:00 +07 → 02:55/03:00 UTC) share the calendar day with their
    UTC form, so re-keying to them keeps every downstream date correct.

    Args:
        prices: Price panel indexed by bar timestamp, one column per symbol.

    Returns:
        The panel with at most one row per trading day. Returned unchanged when
        it already satisfies that (the common case), so this is a no-op on every
        panel written before 2026-08-31.
    """
    if prices.empty or not isinstance(prices.index, pd.DatetimeIndex):
        return prices
    day_key: pd.DatetimeIndex = prices.index.normalize()
    duplicated: Any = day_key.duplicated()
    if not bool(duplicated.any()):
        return prices
    dupe_days: list[str] = [str(d.date()) for d in day_key[duplicated].unique()]
    logger.warning(
        "price panel carries %d day(s) with more than one bar — collapsing to the "
        "union of each day's bars: %s",
        len(dupe_days),
        dupe_days,
    )
    collapsed: pd.DataFrame = prices.groupby(day_key).last()
    last_ts: pd.Series = prices.index.to_series().groupby(day_key).last()
    collapsed.index = pd.DatetimeIndex(last_ts)
    collapsed.index.name = prices.index.name
    return collapsed


def drop_unpriced_days(panel: pd.DataFrame, *, context: str) -> pd.DataFrame:
    """Drop days on which any held symbol has no price, and say which.

    ``DataFrame.sum(axis=1)`` defaults to ``skipna=True``, so an unpriced holding
    contributes **zero market value** rather than propagating NaN. That turns a
    missing input into a confident, plausible, wrong number — it is what made the
    2026-09-01 corruption silent rather than obviously broken, and it is why this
    guard exists in addition to :func:`collapse_to_daily_bars`.

    A day on which the book cannot be fully valued is **undefined, not smaller**,
    so it is dropped rather than valued. Callers fail closed on the result: an
    empty panel yields no metrics and no row is written, which keeps "we could not
    price the book" distinguishable from "the book fell".

    No cross-day forward-fill is applied. Carrying a stale price into a session
    the instrument did not trade is a valuation-policy change, not a bug fix.

    Args:
        panel: Price panel restricted to the held symbols.
        context: Caller name, for the log line.

    Returns:
        The panel with any incompletely-priced day removed.
    """
    unpriced: pd.Series = panel.isna().any(axis=1)
    if not bool(unpriced.any()):
        return panel
    for ts in panel.index[unpriced]:
        row: pd.Series = panel.loc[ts]
        logger.warning(
            "%s: dropping %s — no price for %s; the book cannot be valued on that day",
            context,
            pd.Timestamp(ts).date(),
            sorted(row.index[row.isna()].tolist()),
        )
    return panel.loc[~unpriced]


def compute_live_portfolio_metrics(
    config: LivePortfolioConfig,
    prices: pd.DataFrame,
) -> LivePortfolioMetrics | None:
    """Reprice the held positions against ``prices`` and derive daily metrics.

    Args:
        config: The live-portfolio config.
        prices: DataFrame of close prices indexed by trading day (tz-aware
            or naive) with one column per qualified symbol
            (e.g. ``SET:DELTA``).

    Returns:
        :class:`LivePortfolioMetrics` for the most recent trading day on or
        after the entry date, or ``None`` when ``prices`` is empty, lacks
        any held symbol, or has no rows on/after entry.
    """
    if prices.empty:
        return None
    symbols: list[str] = [p.qualified_symbol for p in config.positions]
    missing: list[str] = [s for s in symbols if s not in prices.columns]
    if missing:
        logger.warning("live_portfolio: prices missing required symbols: %s", missing)
        return None

    entry_ts: pd.Timestamp = pd.Timestamp(config.entry_date)
    index_tz: Any = prices.index.tz
    if index_tz is not None:
        entry_ts = (
            entry_ts.tz_localize(index_tz) if entry_ts.tz is None else entry_ts.tz_convert(index_tz)
        )
    panel: pd.DataFrame = prices.loc[prices.index >= entry_ts, symbols]
    if panel.empty:
        logger.warning(
            "live_portfolio: no rows in prices_latest at or after entry_date=%s",
            config.entry_date.isoformat(),
        )
        return None
    # One row per BAR is not one row per DAY, and `nav.iloc[-1]` below assumes the
    # latter. Collapse first, then refuse to value any day that is not fully priced
    # — the `missing` check above only proves the COLUMNS exist, never the values.
    panel = collapse_to_daily_bars(panel)
    panel = drop_unpriced_days(panel, context="live_portfolio")
    if panel.empty:
        logger.warning(
            "live_portfolio: no fully-priced trading day at or after entry_date=%s — "
            "refusing to derive metrics rather than valuing an incomplete book",
            config.entry_date.isoformat(),
        )
        return None

    shares: pd.Series = pd.Series(
        {p.qualified_symbol: float(p.shares) for p in config.positions},
        dtype="float64",
    )
    market_value: pd.Series = panel.mul(shares, axis=1).sum(axis=1)
    nav: pd.Series = market_value + float(config.cash)

    total_value: float = float(nav.iloc[-1])
    if len(nav) >= 2:
        prev_nav: float = float(nav.iloc[-2])
        daily_return: float = (total_value / prev_nav) - 1.0
        daily_pnl: float = float(market_value.iloc[-1] - market_value.iloc[-2])
    else:
        daily_return = (total_value / float(config.starting_nav)) - 1.0
        daily_pnl = float(total_value - config.starting_nav)
    cumulative_return: float = (total_value / float(config.starting_nav)) - 1.0

    nav_with_start: pd.Series = pd.concat(
        [pd.Series([float(config.starting_nav)], index=[nav.index[0] - pd.Timedelta(days=1)]), nav]
    )
    peak: pd.Series = nav_with_start.cummax()
    drawdown_series: pd.Series = nav_with_start / peak - 1.0
    max_drawdown: float = float(drawdown_series.min())

    daily_returns: pd.Series = nav.pct_change().dropna()
    if len(daily_returns) >= SHARPE_MIN_SAMPLE:
        std_r: float = float(daily_returns.std(ddof=1))
        mean_r: float = float(daily_returns.mean())
        sharpe_ratio: float = (
            (mean_r / std_r) * float(np.sqrt(TRADING_DAYS_PER_YEAR)) if std_r > 0 else 0.0
        )
    else:
        sharpe_ratio = 0.0

    snapshot_ts: pd.Timestamp = pd.Timestamp(nav.index[-1])
    return LivePortfolioMetrics(
        snapshot_time=snapshot_ts.to_pydatetime(),
        total_value=total_value,
        cash_balance=float(config.cash),
        daily_return=daily_return,
        cumulative_return=cumulative_return,
        max_drawdown=max_drawdown,
        sharpe_ratio=sharpe_ratio,
        daily_pnl=daily_pnl,
        positions_count=len(config.positions),
    )


__all__: list[str] = [
    "LivePortfolioConfig",
    "LivePortfolioMetrics",
    "LivePosition",
    "SHARPE_MIN_SAMPLE",
    "TRADING_DAYS_PER_YEAR",
    "collapse_to_daily_bars",
    "drop_unpriced_days",
    "compute_live_portfolio_metrics",
    "load_live_portfolio",
]
