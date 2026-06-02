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
    "compute_live_portfolio_metrics",
    "load_live_portfolio",
]
