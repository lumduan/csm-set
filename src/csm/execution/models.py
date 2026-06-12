"""Local Pydantic mirrors of the Execution engine wire contract (Phase 5.1).

These models mirror the ``quant-execution-engine`` order contract closely enough
to (de)serialize requests and SSE events, but are **deliberately independent** —
csm-set never imports across the repo boundary. The mirror is SET-only: every
order omits ``position_effect`` (required only for TFEX) and pins ``market`` to
``"SET"``.

Wire rules:

- Money is ``Decimal`` end-to-end. :data:`WireDecimal` serializes to a plain
  (non-scientific) string on the JSON wire; the engine rejects floats.
- :meth:`NormalizedOrder.wire_dump` uses ``exclude_none=True`` so optional fields
  (notably ``position_effect``, which this mirror never declares, plus null prices)
  are omitted entirely.

Also defined here are the small sim-loop value objects (:class:`OrderInstruction`,
:class:`SimPosition`, :class:`SimPortfolio`) that have no engine counterpart.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from csm.execution.errors import SimLoopError

# --- Literal type aliases (mirror the engine enums) -------------------------

BrokerName = Literal["sim", "liberator", "settrade"]
OrderSide = Literal["BUY", "SELL"]
OrderTypeName = Literal["MARKET", "LIMIT", "STOP", "STOP_LIMIT", "ICEBERG", "MTL", "ATO", "ATC"]
TifName = Literal["DAY", "IOC", "FOK", "GTC"]
EngineState = Literal[
    "PENDING_NEW",
    "NEW",
    "PARTIALLY_FILLED",
    "FILLED",
    "PENDING_CANCEL",
    "PENDING_REPLACE",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
]
PublicStatus = Literal[
    "NEW",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
]

TERMINAL_STATES: frozenset[str] = frozenset({"FILLED", "CANCELLED", "REJECTED", "EXPIRED"})

# Decimal-as-string on the JSON wire (no scientific notation, never float).
WireDecimal = Annotated[
    Decimal,
    PlainSerializer(lambda d: format(d, "f"), return_type=str, when_used="json"),
]


# --- Order request / result mirrors -----------------------------------------


class NormalizedOrder(BaseModel):
    """SET-only mirror of the engine ``NormalizedOrder`` request body.

    ``market`` is pinned to ``"SET"`` and ``position_effect`` is intentionally
    absent — SET orders must omit it. ``wire_dump`` drops all ``None`` fields so
    the serialized body matches the engine's expectations exactly.
    """

    model_config = ConfigDict(frozen=True)

    client_order_id: str = Field(description="Caller-generated UUIDv4 order id.")
    broker: BrokerName = Field(description="Target broker.")
    account: str = Field(min_length=1, description="Broker account identifier.")
    market: Literal["SET"] = Field(default="SET", description="Always SET for csm-set.")
    symbol: str = Field(min_length=1, description="SET ticker symbol.")
    side: OrderSide = Field(description="Order side.")
    order_type: OrderTypeName = Field(default="LIMIT", description="Order type.")
    price: WireDecimal | None = Field(default=None, description="Limit price (Decimal).")
    stop_price: WireDecimal | None = Field(default=None, description="Stop trigger price.")
    quantity: int = Field(gt=0, description="Order quantity in shares.")
    tif: TifName = Field(default="DAY", description="Time in force.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Opaque metadata.")

    def wire_dump(self) -> dict[str, Any]:
        """Return the JSON-ready request body with all ``None`` fields removed."""
        return self.model_dump(mode="json", exclude_none=True)


class NormalizedOrderResult(BaseModel):
    """Mirror of the engine order result (POST ack / GET response body)."""

    model_config = ConfigDict(frozen=True)

    client_order_id: str
    broker_order_id: str | None = None
    broker: str
    status: PublicStatus
    engine_state: EngineState
    filled_qty: int = 0
    remaining_qty: int = 0
    avg_fill_price: Decimal | None = None
    reject_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    @property
    def is_terminal(self) -> bool:
        """True when the order has reached a terminal engine state."""
        return self.engine_state in TERMINAL_STATES


class FillEvent(BaseModel):
    """A single execution (fill) embedded in an order-update event."""

    model_config = ConfigDict(frozen=True)

    broker_fill_id: str
    price: Decimal
    quantity: int
    exec_ts: datetime


class OrderUpdateEvent(BaseModel):
    """Mirror of the SSE ``OrderUpdateEvent`` payload (the ``data:`` field)."""

    model_config = ConfigDict(frozen=True)

    seq: int
    client_order_id: str
    strategy_id: str | None = None
    engine_state: EngineState
    status: PublicStatus
    broker_order_id: str | None = None
    price: Decimal | None = None
    quantity: int | None = None
    fill: FillEvent | None = None
    ts: datetime

    @property
    def is_terminal(self) -> bool:
        """True when this event marks the order terminal."""
        return self.engine_state in TERMINAL_STATES


# --- Sim-loop value objects (no engine counterpart) -------------------------


class OrderInstruction(BaseModel):
    """A resolved per-symbol order intent prior to NormalizedOrder construction."""

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1)
    side: OrderSide
    quantity: int = Field(gt=0)
    limit_price: Decimal = Field(gt=0)


class SimPosition(BaseModel):
    """A single long-only simulated position."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    quantity: int = 0
    avg_price: Decimal = Decimal("0")


class SimPortfolio(BaseModel):
    """A mutable bag of simulated positions keyed by symbol."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    positions: dict[str, SimPosition] = Field(default_factory=dict)

    def apply_fill(self, symbol: str, side: OrderSide, quantity: int, price: Decimal) -> None:
        """Apply one fill to the position book (long-only).

        BUY raises the weighted-average cost and quantity. SELL reduces quantity
        (average cost unchanged). Selling more than held is not clamped silently —
        csm-set is long-only, so an oversell raises :class:`SimLoopError`.
        """
        if quantity <= 0:
            raise SimLoopError(f"fill quantity must be positive for {symbol!r}, got {quantity}")
        current = self.positions.get(symbol, SimPosition(symbol=symbol))
        if side == "BUY":
            new_qty = current.quantity + quantity
            total_cost = current.avg_price * current.quantity + price * quantity
            new_avg = total_cost / new_qty
            self.positions[symbol] = SimPosition(symbol=symbol, quantity=new_qty, avg_price=new_avg)
        else:  # SELL
            new_qty = current.quantity - quantity
            if new_qty < 0:
                raise SimLoopError(
                    f"oversell on {symbol!r}: sold {quantity} but only held "
                    f"{current.quantity} (csm-set is long-only)"
                )
            self.positions[symbol] = SimPosition(
                symbol=symbol, quantity=new_qty, avg_price=current.avg_price
            )


__all__: list[str] = [
    "TERMINAL_STATES",
    "BrokerName",
    "EngineState",
    "FillEvent",
    "NormalizedOrder",
    "NormalizedOrderResult",
    "OrderInstruction",
    "OrderSide",
    "OrderTypeName",
    "OrderUpdateEvent",
    "PublicStatus",
    "SimPortfolio",
    "SimPosition",
    "TifName",
    "WireDecimal",
]
