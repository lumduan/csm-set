"""Pair a stream of rebalance fills into round-trip ``ClosedTrade`` records.

The csm-set engine emits one rebalance fill per (date, symbol, side, shares,
price, commission) tuple. To build the TradingView-style trade log, those
fills must be aggregated into entry/exit pairs per symbol using a FIFO lot
queue. Each fill that opens (or adds to) an inventory lot is later closed —
in arrival order — by one or more opposite-side fills.

This module is pure-function, dependency-free apart from Pydantic v2 and the
standard library; it is exercised by ``csm.research.strategy_report`` and the
post-refresh hook.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from csm.execution.errors import TradePairingError

logger: logging.Logger = logging.getLogger(__name__)


PositionSide = Literal["LONG", "SHORT"]


class RebalanceFill(BaseModel):
    """A single rebalance fill from the strategy engine.

    Attributes:
        time: tz-aware UTC timestamp of the fill.
        symbol: SET ticker (e.g. ``"DELTA"`` or qualified ``"SET:DELTA"``).
        side: ``"BUY"`` (add long / cover short) or ``"SELL"`` (reduce long /
            open short).
        shares: Positive integer-equivalent quantity. Decimal for precision.
        price: Fill price in THB.
        commission: Per-fill commission in THB; defaults to zero.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    time: datetime
    symbol: str
    side: Literal["BUY", "SELL"]
    shares: Decimal = Field(gt=Decimal("0"))
    price: Decimal = Field(gt=Decimal("0"))
    commission: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))

    @field_validator("time")
    @classmethod
    def _time_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            msg = "RebalanceFill.time must be tz-aware (UTC)"
            raise ValueError(msg)
        if value.utcoffset() != UTC.utcoffset(value):
            return value.astimezone(UTC)
        return value


class ClosedTrade(BaseModel):
    """A paired round-trip trade — entry+exit on one symbol.

    Monetary fields are ``Decimal`` end-to-end. ``side`` reflects the
    *position* held between entry and exit (LONG = bought-then-sold,
    SHORT = sold-then-bought).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    side: PositionSide
    entry_time: datetime
    exit_time: datetime
    entry_price: Decimal
    exit_price: Decimal
    qty: Decimal = Field(gt=Decimal("0"))
    realized_pnl: Decimal
    duration_bars: int = Field(ge=0)
    commission: Decimal = Field(ge=Decimal("0"))

    @field_validator("entry_time", "exit_time")
    @classmethod
    def _utc_only(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            msg = "ClosedTrade timestamps must be tz-aware (UTC)"
            raise ValueError(msg)
        return value.astimezone(UTC)


def pair_trades(fills: Iterable[RebalanceFill]) -> list[ClosedTrade]:
    """Pair a sequence of rebalance fills into ``ClosedTrade`` records (FIFO).

    The algorithm walks the fills in arrival order, maintaining one FIFO
    inventory queue per symbol. Each BUY pushes a lot onto the queue; each
    SELL pops lots in FIFO order, emitting one ``ClosedTrade`` per
    (entry-lot, exit-share-slice) pair. Re-entries after a flat position
    start a fresh lot.

    Short-side pairing mirrors the long flow: a SELL on a flat book opens a
    SHORT lot, a subsequent BUY closes it. Mixed long+short on the same
    symbol within a single fill stream is not supported and raises
    :class:`TradePairingError`.

    Args:
        fills: An iterable of :class:`RebalanceFill`. Order is preserved.

    Returns:
        A list of :class:`ClosedTrade` records in exit-time order (i.e. the
        order in which the closing fill arrived).

    Raises:
        TradePairingError: When a fill would flip an open long/short
            position to the opposite side without first going flat
            (csm-set's long-only engine never produces this, but the
            invariant guards future strategies).
    """

    lots_by_symbol: dict[str, deque[_OpenLot]] = {}
    closed: list[ClosedTrade] = []

    fills_list: list[RebalanceFill] = list(fills)
    fills_list.sort(key=lambda f: (f.time, f.symbol))

    for fill in fills_list:
        queue: deque[_OpenLot] = lots_by_symbol.setdefault(fill.symbol, deque())
        if not queue:
            queue.append(
                _OpenLot(
                    side="LONG" if fill.side == "BUY" else "SHORT",
                    time=fill.time,
                    price=fill.price,
                    shares=fill.shares,
                    commission=fill.commission,
                )
            )
            continue

        head: _OpenLot = queue[0]
        is_opening: bool = (head.side == "LONG" and fill.side == "BUY") or (
            head.side == "SHORT" and fill.side == "SELL"
        )
        if is_opening:
            queue.append(
                _OpenLot(
                    side=head.side,
                    time=fill.time,
                    price=fill.price,
                    shares=fill.shares,
                    commission=fill.commission,
                )
            )
            continue

        remaining: Decimal = fill.shares
        per_exit_share_commission: Decimal = (
            fill.commission / fill.shares if fill.shares > 0 else Decimal("0")
        )
        while remaining > 0 and queue:
            lot: _OpenLot = queue[0]
            consumed: Decimal = min(lot.shares, remaining)
            entry_portion_commission: Decimal = (
                lot.commission * (consumed / lot.shares) if lot.shares > 0 else Decimal("0")
            )
            exit_portion_commission: Decimal = per_exit_share_commission * consumed
            commission_total: Decimal = entry_portion_commission + exit_portion_commission

            if lot.side == "LONG":
                gross: Decimal = (fill.price - lot.price) * consumed
            else:
                gross = (lot.price - fill.price) * consumed
            realized: Decimal = gross - commission_total

            duration_bars: int = max(int((fill.time.date() - lot.time.date()).days), 0)

            closed.append(
                ClosedTrade(
                    symbol=fill.symbol,
                    side=lot.side,
                    entry_time=lot.time,
                    exit_time=fill.time,
                    entry_price=lot.price,
                    exit_price=fill.price,
                    qty=consumed,
                    realized_pnl=realized,
                    duration_bars=duration_bars,
                    commission=commission_total,
                )
            )

            lot.shares -= consumed
            lot.commission -= entry_portion_commission
            if lot.shares <= 0:
                queue.popleft()
            remaining -= consumed

        if remaining > 0:
            if queue:
                msg = (
                    f"Trade pairing for {fill.symbol} would flip an open position "
                    "to the opposite side without going flat first; the FIFO queue "
                    "still has open lots after the fill was exhausted."
                )
                raise TradePairingError(msg)
            queue.append(
                _OpenLot(
                    side="SHORT" if fill.side == "SELL" else "LONG",
                    time=fill.time,
                    price=fill.price,
                    shares=remaining,
                    commission=per_exit_share_commission * remaining,
                )
            )

    closed.sort(key=lambda t: (t.exit_time, t.symbol))
    logger.debug("paired %d fills into %d closed trades", len(fills_list), len(closed))
    return closed


class _OpenLot:
    """Mutable FIFO inventory lot — internal to :func:`pair_trades`."""

    __slots__ = ("side", "time", "price", "shares", "commission")

    def __init__(
        self,
        *,
        side: PositionSide,
        time: datetime,
        price: Decimal,
        shares: Decimal,
        commission: Decimal,
    ) -> None:
        self.side: PositionSide = side
        self.time: datetime = time
        self.price: Decimal = price
        self.shares: Decimal = shares
        self.commission: Decimal = commission


__all__: list[str] = ["ClosedTrade", "RebalanceFill", "pair_trades"]
