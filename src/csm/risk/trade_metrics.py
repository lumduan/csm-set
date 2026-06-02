"""Trade-based performance metric helpers (Phase 1 strategy-report).

Stand-alone functions consuming a :class:`Sequence[ClosedTrade]` and
returning ``Decimal`` results. Pure compute, no side effects. Empty inputs
return ``Decimal("0")`` so the downstream JSON stays serialisable; the
caller is responsible for distinguishing "no data" from "all zero" via the
trade-count fields elsewhere in the report.

All ratio fields that would divide by zero (e.g. ``profit_factor`` when
``gross_loss == 0``) return ``Decimal("0")`` and emit a DEBUG log so the
operator can confirm the gate triggered without polluting the production
log stream.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from decimal import Decimal

from csm.execution.trade_pairing import ClosedTrade

logger: logging.Logger = logging.getLogger(__name__)

ZERO: Decimal = Decimal("0")


def gross_profit(trades: Sequence[ClosedTrade]) -> Decimal:
    """Sum of ``realized_pnl`` over all winning trades."""

    return sum((t.realized_pnl for t in trades if t.realized_pnl > ZERO), start=ZERO)


def gross_loss(trades: Sequence[ClosedTrade]) -> Decimal:
    """Sum of ``realized_pnl`` over all losing trades (negative or zero)."""

    return sum((t.realized_pnl for t in trades if t.realized_pnl < ZERO), start=ZERO)


def net_pnl(trades: Sequence[ClosedTrade]) -> Decimal:
    """Sum of ``realized_pnl`` over all trades."""

    return sum((t.realized_pnl for t in trades), start=ZERO)


def profit_factor(trades: Sequence[ClosedTrade]) -> Decimal:
    """Ratio of gross profit to absolute gross loss; ``0`` when loss is zero."""

    loss_total: Decimal = gross_loss(trades)
    if loss_total == ZERO:
        logger.debug("profit_factor: gross_loss is zero — returning 0")
        return ZERO
    return gross_profit(trades) / -loss_total


def expected_payoff(trades: Sequence[ClosedTrade]) -> Decimal:
    """Average ``realized_pnl`` per trade; ``0`` when no trades."""

    n: int = len(trades)
    if n == 0:
        return ZERO
    return net_pnl(trades) / Decimal(n)


def winning_trades(trades: Sequence[ClosedTrade]) -> list[ClosedTrade]:
    """Sub-list of trades with positive ``realized_pnl``."""

    return [t for t in trades if t.realized_pnl > ZERO]


def losing_trades(trades: Sequence[ClosedTrade]) -> list[ClosedTrade]:
    """Sub-list of trades with negative ``realized_pnl``."""

    return [t for t in trades if t.realized_pnl < ZERO]


def avg_winning_trade(trades: Sequence[ClosedTrade]) -> Decimal:
    """Average ``realized_pnl`` over winning trades; ``0`` when none."""

    wins: list[ClosedTrade] = winning_trades(trades)
    if not wins:
        return ZERO
    return gross_profit(wins) / Decimal(len(wins))


def avg_losing_trade(trades: Sequence[ClosedTrade]) -> Decimal:
    """Average ``realized_pnl`` over losing trades; ``0`` when none."""

    losses: list[ClosedTrade] = losing_trades(trades)
    if not losses:
        return ZERO
    return gross_loss(losses) / Decimal(len(losses))


def largest_winning_trade(trades: Sequence[ClosedTrade]) -> Decimal:
    """Maximum ``realized_pnl`` across winning trades; ``0`` when none."""

    wins: list[ClosedTrade] = winning_trades(trades)
    if not wins:
        return ZERO
    return max(t.realized_pnl for t in wins)


def largest_losing_trade(trades: Sequence[ClosedTrade]) -> Decimal:
    """Minimum (most-negative) ``realized_pnl`` across losing trades; ``0`` when none."""

    losses: list[ClosedTrade] = losing_trades(trades)
    if not losses:
        return ZERO
    return min(t.realized_pnl for t in losses)


def pct_profitable(trades: Sequence[ClosedTrade]) -> Decimal:
    """Fraction of trades that are profitable (winners / total); ``0`` when no trades."""

    n: int = len(trades)
    if n == 0:
        return ZERO
    return Decimal(len(winning_trades(trades))) / Decimal(n)


def ratio_avg_win_avg_loss(trades: Sequence[ClosedTrade]) -> Decimal:
    """Ratio of |avg winning trade| to |avg losing trade|; ``0`` when loss avg is zero."""

    loss_avg: Decimal = avg_losing_trade(trades)
    if loss_avg == ZERO:
        return ZERO
    return avg_winning_trade(trades) / -loss_avg


def outliers_count(
    trades: Sequence[ClosedTrade], *, threshold_multiple: Decimal = Decimal("3")
) -> int:
    """Count trades whose ``|realized_pnl|`` exceeds ``threshold_multiple × avg |pnl|``.

    A simple statistical-outlier flag matching the TradingView "outliers"
    column. ``threshold_multiple`` defaults to 3× (≈ 3-sigma when realized
    P&L is approximately normal).
    """

    if not trades:
        return 0
    avg_abs: Decimal = sum((abs(t.realized_pnl) for t in trades), start=ZERO) / Decimal(len(trades))
    if avg_abs == ZERO:
        return 0
    cutoff: Decimal = avg_abs * threshold_multiple
    return sum(1 for t in trades if abs(t.realized_pnl) > cutoff)


def outliers_pnl(
    trades: Sequence[ClosedTrade], *, threshold_multiple: Decimal = Decimal("3")
) -> Decimal:
    """Sum of ``realized_pnl`` over outlier trades.

    Outliers defined as in :func:`outliers_count`.
    """

    if not trades:
        return ZERO
    avg_abs: Decimal = sum((abs(t.realized_pnl) for t in trades), start=ZERO) / Decimal(len(trades))
    if avg_abs == ZERO:
        return ZERO
    cutoff: Decimal = avg_abs * threshold_multiple
    return sum((t.realized_pnl for t in trades if abs(t.realized_pnl) > cutoff), start=ZERO)


def avg_bars_in_trades(trades: Sequence[ClosedTrade]) -> Decimal:
    """Mean ``duration_bars`` across all trades; ``0`` when none."""

    n: int = len(trades)
    if n == 0:
        return ZERO
    return sum((Decimal(t.duration_bars) for t in trades), start=ZERO) / Decimal(n)


def avg_bars_in_winning_trades(trades: Sequence[ClosedTrade]) -> Decimal:
    """Mean ``duration_bars`` across winning trades; ``0`` when none."""

    wins: list[ClosedTrade] = winning_trades(trades)
    return avg_bars_in_trades(wins)


def avg_bars_in_losing_trades(trades: Sequence[ClosedTrade]) -> Decimal:
    """Mean ``duration_bars`` across losing trades; ``0`` when none."""

    losses: list[ClosedTrade] = losing_trades(trades)
    return avg_bars_in_trades(losses)


def longest_winning_streak(trades: Sequence[ClosedTrade]) -> int:
    """Longest consecutive run of winning trades in arrival order."""

    longest: int = 0
    current: int = 0
    for trade in trades:
        if trade.realized_pnl > ZERO:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def longest_losing_streak(trades: Sequence[ClosedTrade]) -> int:
    """Longest consecutive run of losing trades in arrival order."""

    longest: int = 0
    current: int = 0
    for trade in trades:
        if trade.realized_pnl < ZERO:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


__all__: list[str] = [
    "avg_bars_in_losing_trades",
    "avg_bars_in_trades",
    "avg_bars_in_winning_trades",
    "avg_losing_trade",
    "avg_winning_trade",
    "expected_payoff",
    "gross_loss",
    "gross_profit",
    "largest_losing_trade",
    "largest_winning_trade",
    "longest_losing_streak",
    "longest_winning_streak",
    "losing_trades",
    "net_pnl",
    "outliers_count",
    "outliers_pnl",
    "pct_profitable",
    "profit_factor",
    "ratio_avg_win_avg_loss",
    "winning_trades",
]
