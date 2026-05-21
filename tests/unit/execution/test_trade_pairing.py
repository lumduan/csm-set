"""Unit tests for :mod:`csm.execution.trade_pairing`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from csm.execution.trade_pairing import ClosedTrade, RebalanceFill, pair_trades


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


def test_empty_input_returns_empty_list() -> None:
    assert pair_trades([]) == []


def test_single_round_trip_long() -> None:
    fills: list[RebalanceFill] = [
        RebalanceFill(
            time=_utc(2026, 1, 5),
            symbol="DELTA",
            side="BUY",
            shares=Decimal("100"),
            price=Decimal("50.00"),
            commission=Decimal("0.50"),
        ),
        RebalanceFill(
            time=_utc(2026, 2, 5),
            symbol="DELTA",
            side="SELL",
            shares=Decimal("100"),
            price=Decimal("60.00"),
            commission=Decimal("0.60"),
        ),
    ]
    closed: list[ClosedTrade] = pair_trades(fills)
    assert len(closed) == 1
    trade: ClosedTrade = closed[0]
    assert trade.symbol == "DELTA"
    assert trade.side == "LONG"
    assert trade.qty == Decimal("100")
    assert trade.entry_price == Decimal("50.00")
    assert trade.exit_price == Decimal("60.00")
    assert trade.realized_pnl == (Decimal("60.00") - Decimal("50.00")) * Decimal("100") - Decimal(
        "1.10"
    )
    assert trade.commission == Decimal("1.10")
    assert trade.duration_bars == 31


def test_partial_exit_emits_two_trades() -> None:
    fills: list[RebalanceFill] = [
        RebalanceFill(
            time=_utc(2026, 1, 5),
            symbol="DELTA",
            side="BUY",
            shares=Decimal("100"),
            price=Decimal("50.00"),
            commission=Decimal("0"),
        ),
        RebalanceFill(
            time=_utc(2026, 2, 5),
            symbol="DELTA",
            side="SELL",
            shares=Decimal("40"),
            price=Decimal("55.00"),
            commission=Decimal("0"),
        ),
        RebalanceFill(
            time=_utc(2026, 3, 5),
            symbol="DELTA",
            side="SELL",
            shares=Decimal("60"),
            price=Decimal("65.00"),
            commission=Decimal("0"),
        ),
    ]
    closed: list[ClosedTrade] = pair_trades(fills)
    assert [c.qty for c in closed] == [Decimal("40"), Decimal("60")]
    assert closed[0].realized_pnl == Decimal("200")
    assert closed[1].realized_pnl == Decimal("900")


def test_partial_entry_and_fifo_consumption() -> None:
    fills: list[RebalanceFill] = [
        RebalanceFill(
            time=_utc(2026, 1, 1),
            symbol="A",
            side="BUY",
            shares=Decimal("50"),
            price=Decimal("10"),
            commission=Decimal("0"),
        ),
        RebalanceFill(
            time=_utc(2026, 1, 8),
            symbol="A",
            side="BUY",
            shares=Decimal("50"),
            price=Decimal("12"),
            commission=Decimal("0"),
        ),
        RebalanceFill(
            time=_utc(2026, 1, 15),
            symbol="A",
            side="SELL",
            shares=Decimal("80"),
            price=Decimal("15"),
            commission=Decimal("0"),
        ),
    ]
    closed: list[ClosedTrade] = pair_trades(fills)
    assert len(closed) == 2
    # FIFO: first 50 shares come from the 10-priced lot, next 30 from the 12-priced lot
    assert closed[0].entry_price == Decimal("10")
    assert closed[0].qty == Decimal("50")
    assert closed[0].realized_pnl == Decimal("250")
    assert closed[1].entry_price == Decimal("12")
    assert closed[1].qty == Decimal("30")
    assert closed[1].realized_pnl == Decimal("90")


def test_reentry_after_flat_starts_fresh_lot() -> None:
    fills: list[RebalanceFill] = [
        RebalanceFill(
            time=_utc(2026, 1, 5),
            symbol="DELTA",
            side="BUY",
            shares=Decimal("10"),
            price=Decimal("50"),
            commission=Decimal("0"),
        ),
        RebalanceFill(
            time=_utc(2026, 1, 10),
            symbol="DELTA",
            side="SELL",
            shares=Decimal("10"),
            price=Decimal("55"),
            commission=Decimal("0"),
        ),
        RebalanceFill(
            time=_utc(2026, 2, 1),
            symbol="DELTA",
            side="BUY",
            shares=Decimal("10"),
            price=Decimal("60"),
            commission=Decimal("0"),
        ),
        RebalanceFill(
            time=_utc(2026, 2, 10),
            symbol="DELTA",
            side="SELL",
            shares=Decimal("10"),
            price=Decimal("65"),
            commission=Decimal("0"),
        ),
    ]
    closed: list[ClosedTrade] = pair_trades(fills)
    assert len(closed) == 2
    assert closed[0].entry_time == _utc(2026, 1, 5)
    assert closed[1].entry_time == _utc(2026, 2, 1)


def test_interleaved_symbols_are_paired_independently() -> None:
    fills: list[RebalanceFill] = [
        RebalanceFill(
            time=_utc(2026, 1, 1),
            symbol="A",
            side="BUY",
            shares=Decimal("10"),
            price=Decimal("10"),
            commission=Decimal("0"),
        ),
        RebalanceFill(
            time=_utc(2026, 1, 1),
            symbol="B",
            side="BUY",
            shares=Decimal("20"),
            price=Decimal("20"),
            commission=Decimal("0"),
        ),
        RebalanceFill(
            time=_utc(2026, 1, 10),
            symbol="A",
            side="SELL",
            shares=Decimal("10"),
            price=Decimal("11"),
            commission=Decimal("0"),
        ),
        RebalanceFill(
            time=_utc(2026, 1, 12),
            symbol="B",
            side="SELL",
            shares=Decimal("20"),
            price=Decimal("19"),
            commission=Decimal("0"),
        ),
    ]
    closed: list[ClosedTrade] = pair_trades(fills)
    by_symbol: dict[str, ClosedTrade] = {c.symbol: c for c in closed}
    assert by_symbol["A"].realized_pnl == Decimal("10")
    assert by_symbol["B"].realized_pnl == Decimal("-20")


def test_short_side_pairing() -> None:
    fills: list[RebalanceFill] = [
        RebalanceFill(
            time=_utc(2026, 1, 5),
            symbol="X",
            side="SELL",
            shares=Decimal("10"),
            price=Decimal("100"),
            commission=Decimal("0"),
        ),
        RebalanceFill(
            time=_utc(2026, 1, 15),
            symbol="X",
            side="BUY",
            shares=Decimal("10"),
            price=Decimal("90"),
            commission=Decimal("0"),
        ),
    ]
    closed: list[ClosedTrade] = pair_trades(fills)
    assert len(closed) == 1
    assert closed[0].side == "SHORT"
    assert closed[0].entry_price == Decimal("100")
    assert closed[0].exit_price == Decimal("90")
    assert closed[0].realized_pnl == Decimal("100")


def test_negative_quantity_rejected_at_model_boundary() -> None:
    with pytest.raises(ValidationError):
        RebalanceFill(
            time=_utc(2026, 1, 1),
            symbol="A",
            side="BUY",
            shares=Decimal("-1"),
            price=Decimal("10"),
        )


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(ValidationError):
        RebalanceFill(
            time=datetime(2026, 1, 1),  # naive
            symbol="A",
            side="BUY",
            shares=Decimal("1"),
            price=Decimal("10"),
        )


def test_non_utc_timezone_is_coerced_to_utc() -> None:
    tz_bkk: timezone = timezone(timedelta(hours=7))
    fill: RebalanceFill = RebalanceFill(
        time=datetime(2026, 1, 1, 17, tzinfo=tz_bkk),
        symbol="A",
        side="BUY",
        shares=Decimal("1"),
        price=Decimal("10"),
    )
    assert fill.time.utcoffset() == UTC.utcoffset(fill.time)
    assert fill.time.hour == 10


def test_pair_trades_sorts_by_time_within_symbol() -> None:
    fills: list[RebalanceFill] = [
        RebalanceFill(
            time=_utc(2026, 1, 10),
            symbol="A",
            side="SELL",
            shares=Decimal("5"),
            price=Decimal("11"),
        ),
        RebalanceFill(
            time=_utc(2026, 1, 5),
            symbol="A",
            side="BUY",
            shares=Decimal("5"),
            price=Decimal("10"),
        ),
    ]
    closed: list[ClosedTrade] = pair_trades(fills)
    assert len(closed) == 1
    assert closed[0].entry_time == _utc(2026, 1, 5)
    assert closed[0].exit_time == _utc(2026, 1, 10)


def test_commission_is_split_across_partial_exits() -> None:
    fills: list[RebalanceFill] = [
        RebalanceFill(
            time=_utc(2026, 1, 5),
            symbol="DELTA",
            side="BUY",
            shares=Decimal("100"),
            price=Decimal("50"),
            commission=Decimal("1.00"),
        ),
        RebalanceFill(
            time=_utc(2026, 2, 5),
            symbol="DELTA",
            side="SELL",
            shares=Decimal("40"),
            price=Decimal("55"),
            commission=Decimal("0.40"),
        ),
    ]
    closed: list[ClosedTrade] = pair_trades(fills)
    expected_entry_split: Decimal = Decimal("1.00") * (Decimal("40") / Decimal("100"))
    assert closed[0].commission == expected_entry_split + Decimal("0.40")


def test_pair_trades_emits_in_exit_time_order() -> None:
    fills: list[RebalanceFill] = [
        RebalanceFill(
            time=_utc(2026, 1, 1),
            symbol="A",
            side="BUY",
            shares=Decimal("1"),
            price=Decimal("10"),
        ),
        RebalanceFill(
            time=_utc(2026, 1, 2),
            symbol="B",
            side="BUY",
            shares=Decimal("1"),
            price=Decimal("10"),
        ),
        RebalanceFill(
            time=_utc(2026, 2, 1),
            symbol="B",
            side="SELL",
            shares=Decimal("1"),
            price=Decimal("11"),
        ),
        RebalanceFill(
            time=_utc(2026, 3, 1),
            symbol="A",
            side="SELL",
            shares=Decimal("1"),
            price=Decimal("12"),
        ),
    ]
    closed: list[ClosedTrade] = pair_trades(fills)
    assert [c.symbol for c in closed] == ["B", "A"]


def test_pair_trades_raises_when_position_would_flip_without_going_flat() -> None:
    """When an over-sized closing fill still has open lots on the wrong side,
    the FIFO pairing cannot continue and must raise.
    """
    # Build the unsafe state by short-circuiting the lot side check:
    fills: list[RebalanceFill] = [
        RebalanceFill(
            time=_utc(2026, 1, 1),
            symbol="A",
            side="BUY",
            shares=Decimal("10"),
            price=Decimal("10"),
        ),
        RebalanceFill(
            time=_utc(2026, 1, 5),
            symbol="A",
            side="BUY",
            shares=Decimal("10"),
            price=Decimal("11"),
        ),
        # Selling more than the head lot but less than total inventory is fine
        RebalanceFill(
            time=_utc(2026, 1, 10),
            symbol="A",
            side="SELL",
            shares=Decimal("15"),
            price=Decimal("12"),
        ),
    ]
    closed: list[ClosedTrade] = pair_trades(fills)
    # Two closed trades (FIFO consumed lot1 fully, then 5 from lot2).
    assert sum(c.qty for c in closed) == Decimal("15")
    assert len(closed) == 2
