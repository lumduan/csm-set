"""Unit tests for :mod:`csm.execution.models` (Phase 5.1 wire mirrors)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from csm.execution.errors import SimLoopError
from csm.execution.models import (
    TERMINAL_STATES,
    FillEvent,
    NormalizedOrder,
    NormalizedOrderResult,
    OrderInstruction,
    OrderUpdateEvent,
    SimPortfolio,
    SimPosition,
)

_TS = datetime(2026, 6, 12, 9, 0, tzinfo=UTC)


def _order(**overrides: object) -> NormalizedOrder:
    base: dict[str, object] = {
        "client_order_id": "cid-1",
        "broker": "sim",
        "account": "SIM-1",
        "symbol": "PTT",
        "side": "BUY",
        "price": Decimal("35.50"),
        "quantity": 100,
    }
    base.update(overrides)
    return NormalizedOrder(**base)  # type: ignore[arg-type]


class TestNormalizedOrder:
    def test_price_serialized_as_plain_string(self) -> None:
        body = _order(price=Decimal("35.50")).wire_dump()
        assert body["price"] == "35.50"
        assert isinstance(body["price"], str)

    def test_no_scientific_notation_for_tiny_price(self) -> None:
        body = _order(price=Decimal("0.0001")).wire_dump()
        assert body["price"] == "0.0001"
        assert "E" not in body["price"] and "e" not in body["price"]

    def test_wire_dump_omits_none_and_position_effect(self) -> None:
        body = _order(price=Decimal("10")).wire_dump()
        assert "position_effect" not in body
        assert "stop_price" not in body  # None dropped
        assert body["market"] == "SET"

    def test_wire_dump_is_json_serializable(self) -> None:
        # exclude_none + mode=json means no Decimal leaks through.
        json.dumps(_order().wire_dump())

    def test_market_pinned_to_set(self) -> None:
        with pytest.raises(ValidationError):
            _order(market="TFEX")

    def test_quantity_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            _order(quantity=0)

    def test_account_min_length(self) -> None:
        with pytest.raises(ValidationError):
            _order(account="")

    def test_is_frozen(self) -> None:
        order = _order()
        with pytest.raises(ValidationError):
            order.quantity = 5  # type: ignore[misc]


class TestNormalizedOrderResult:
    def test_parses_avg_fill_price_string(self) -> None:
        result = NormalizedOrderResult.model_validate(
            {
                "client_order_id": "cid-1",
                "broker": "sim",
                "status": "FILLED",
                "engine_state": "FILLED",
                "filled_qty": 100,
                "remaining_qty": 0,
                "avg_fill_price": "35.55",
                "created_at": _TS.isoformat(),
                "updated_at": _TS.isoformat(),
            }
        )
        assert result.avg_fill_price == Decimal("35.55")
        assert result.is_terminal is True

    def test_non_terminal_state(self) -> None:
        result = NormalizedOrderResult.model_validate(
            {
                "client_order_id": "cid-1",
                "broker": "sim",
                "status": "PARTIALLY_FILLED",
                "engine_state": "PARTIALLY_FILLED",
                "filled_qty": 50,
                "remaining_qty": 50,
                "avg_fill_price": "35.55",
                "created_at": _TS.isoformat(),
                "updated_at": _TS.isoformat(),
            }
        )
        assert result.is_terminal is False
        assert result.avg_fill_price == Decimal("35.55")


class TestOrderUpdateEvent:
    def test_parses_fill_and_terminal(self) -> None:
        event = OrderUpdateEvent.model_validate_json(
            json.dumps(
                {
                    "seq": 7,
                    "client_order_id": "cid-1",
                    "strategy_id": "csm-set",
                    "engine_state": "FILLED",
                    "status": "FILLED",
                    "broker_order_id": "B-1",
                    "price": "35.50",
                    "quantity": 100,
                    "fill": {
                        "broker_fill_id": "F-1",
                        "price": "35.55",
                        "quantity": 100,
                        "exec_ts": _TS.isoformat(),
                    },
                    "ts": _TS.isoformat(),
                }
            )
        )
        assert event.seq == 7
        assert event.is_terminal is True
        assert event.fill is not None
        assert event.fill.price == Decimal("35.55")
        assert isinstance(event.fill, FillEvent)

    def test_non_terminal_partial(self) -> None:
        event = OrderUpdateEvent.model_validate_json(
            json.dumps(
                {
                    "seq": 3,
                    "client_order_id": "cid-1",
                    "engine_state": "PARTIALLY_FILLED",
                    "status": "PARTIALLY_FILLED",
                    "ts": _TS.isoformat(),
                }
            )
        )
        assert event.is_terminal is False
        assert event.fill is None
        assert event.strategy_id is None


class TestTerminalStates:
    def test_membership(self) -> None:
        assert frozenset({"FILLED", "CANCELLED", "REJECTED", "EXPIRED"}) == TERMINAL_STATES


class TestSimPortfolio:
    def test_buy_weighted_average(self) -> None:
        book = SimPortfolio()
        book.apply_fill("PTT", "BUY", 100, Decimal("35.00"))
        book.apply_fill("PTT", "BUY", 100, Decimal("37.00"))
        pos = book.positions["PTT"]
        assert pos.quantity == 200
        assert pos.avg_price == Decimal("36.00")

    def test_sell_reduces_quantity_keeps_avg(self) -> None:
        book = SimPortfolio(
            positions={"PTT": SimPosition(symbol="PTT", quantity=100, avg_price=Decimal("35"))}
        )
        book.apply_fill("PTT", "SELL", 40, Decimal("40.00"))
        pos = book.positions["PTT"]
        assert pos.quantity == 60
        assert pos.avg_price == Decimal("35")

    def test_oversell_raises(self) -> None:
        book = SimPortfolio(positions={"PTT": SimPosition(symbol="PTT", quantity=10)})
        with pytest.raises(SimLoopError, match="oversell"):
            book.apply_fill("PTT", "SELL", 11, Decimal("1"))

    def test_zero_quantity_fill_raises(self) -> None:
        book = SimPortfolio()
        with pytest.raises(SimLoopError, match="positive"):
            book.apply_fill("PTT", "BUY", 0, Decimal("1"))


class TestOrderInstruction:
    def test_requires_positive_quantity_and_price(self) -> None:
        with pytest.raises(ValidationError):
            OrderInstruction(symbol="PTT", side="BUY", quantity=0, limit_price=Decimal("1"))
        with pytest.raises(ValidationError):
            OrderInstruction(symbol="PTT", side="BUY", quantity=1, limit_price=Decimal("0"))
