"""End-to-end sim trade loop (Phase 5.1).

Turns a :class:`~csm.execution.trade_list.TradeList` into NormalizedOrders, submits
them through the gateway proxy to the Execution engine SimAdapter, and applies the
resulting SSE fill events to a local :class:`~csm.execution.models.SimPortfolio`.

Loop invariants (per the approved plan):

- **Subscribe-before-submit:** the loop waits (bounded) for the stream consumer's
  connect handshake before the first ``POST`` so no early fill is missed — the
  engine SimAdapter fills synchronously, so a cursor-0 live-only stream opened
  *after* the POST would never see those events. On handshake timeout the loop
  logs a WARNING and proceeds (the GET-residual path still guarantees
  correctness).
- **Single-source fills:** positions move **only** from stream ``fill`` events; the
  POST ack never updates positions (kills the ack-already-FILLED + replay
  double-count class). A client-side seq watermark in the adapter dedupes
  reconnect replays.
- **Residual reconcile:** on per-order timeout or a degraded (reset) stream, the
  loop falls back to ``GET /orders/{cid}`` and applies only the residual
  (``filled_qty − applied_qty``) at ``avg_fill_price``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from csm.config.settings import Settings
from csm.execution.engine_adapter import ExecutionEngineAdapter
from csm.execution.errors import (
    ExecutionModeError,
    OrderRejectedError,
    SimLoopError,
    StreamResetError,
)
from csm.execution.models import (
    EngineState,
    NormalizedOrder,
    OrderInstruction,
    OrderSide,
    OrderUpdateEvent,
    SimPortfolio,
)
from csm.execution.trade_list import TradeList, TradeSide

logger: logging.Logger = logging.getLogger(__name__)

DEFAULT_ORDER_TIMEOUT_SECONDS: float = 30.0
DEFAULT_STREAM_CONNECT_TIMEOUT_SECONDS: float = 10.0


class OrderOutcome(BaseModel):
    """The terminal (or timed-out) outcome of one submitted order."""

    model_config = ConfigDict(frozen=True)

    instruction: OrderInstruction
    client_order_id: str
    final_state: EngineState | None = None
    filled_qty: int = 0
    avg_fill_price: Decimal | None = None
    rejected: bool = False
    reject_code: str | None = None
    reject_message: str | None = None


class SimLoopResult(BaseModel):
    """Aggregate result of one sim-loop run."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    portfolio: SimPortfolio
    outcomes: list[OrderOutcome]
    skipped_symbols: list[str]


def build_order_instructions(
    trade_list: TradeList, prices: Mapping[str, Decimal]
) -> tuple[list[OrderInstruction], list[str]]:
    """Resolve a TradeList into OrderInstructions, collecting skipped symbols.

    HOLD trades and any trade with ``delta_shares == 0`` are skipped. The side is
    BUY when ``delta_shares > 0`` else SELL; quantity is ``abs(delta_shares)``. A
    traded symbol missing from ``prices`` raises :class:`SimLoopError`.
    """
    instructions: list[OrderInstruction] = []
    skipped: list[str] = []
    missing: list[str] = []
    for trade in trade_list.trades:
        if trade.side == TradeSide.HOLD or trade.delta_shares == 0:
            skipped.append(trade.symbol)
            continue
        if trade.symbol not in prices:
            missing.append(trade.symbol)
            continue
        side: OrderSide = "BUY" if trade.delta_shares > 0 else "SELL"
        instructions.append(
            OrderInstruction(
                symbol=trade.symbol,
                side=side,
                quantity=abs(trade.delta_shares),
                limit_price=prices[trade.symbol],
            )
        )
    if missing:
        raise SimLoopError(f"no price for traded symbol(s): {sorted(missing)!r}")
    return instructions, skipped


@dataclass
class _OrderTracker:
    """Per-order mutable state shared between the consumer and awaiter."""

    instruction: OrderInstruction
    applied_qty: int = 0
    applied_cost: Decimal = Decimal("0")
    final_state: EngineState | None = None
    avg_fill_price: Decimal | None = None
    reject: OrderRejectedError | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)


def _build_adapter(settings: Settings) -> ExecutionEngineAdapter:
    """Construct an adapter from settings (validation normally guarantees the fields)."""
    if not settings.gateway_base_url:
        raise ExecutionModeError("CSM_GATEWAY_BASE_URL is required for execution_mode='sim'")
    if settings.gateway_api_key is None:
        raise ExecutionModeError("CSM_GATEWAY_API_KEY is required for execution_mode='sim'")
    return ExecutionEngineAdapter(
        base_url=settings.gateway_base_url,
        api_key=settings.gateway_api_key.get_secret_value(),
    )


async def run_sim_loop(
    trade_list: TradeList,
    prices: Mapping[str, Decimal],
    *,
    settings: Settings,
    portfolio: SimPortfolio | None = None,
    adapter: ExecutionEngineAdapter | None = None,
    order_timeout_seconds: float = DEFAULT_ORDER_TIMEOUT_SECONDS,
    stream_connect_timeout_seconds: float = DEFAULT_STREAM_CONNECT_TIMEOUT_SECONDS,
) -> SimLoopResult:
    """Run the full signal → order → fill loop against the engine SimAdapter.

    Args:
        trade_list: The rebalance trade list to execute.
        prices: Per-symbol limit prices (Decimal). Every traded symbol must be present.
        settings: Application settings; ``execution_mode`` must be ``"sim"``.
        portfolio: Optional starting portfolio (defaults to empty).
        adapter: Optional injected adapter (defaults to one built from settings).
        order_timeout_seconds: Per-order wait for a terminal state before GET fallback.
        stream_connect_timeout_seconds: Bounded wait for the stream connect
            handshake before the first submit (timeout logs a WARNING and proceeds).

    Raises:
        ExecutionModeError: When ``execution_mode != "sim"``.
        SimLoopError: On invalid input (missing price, oversell).
    """
    if settings.execution_mode != "sim":
        raise ExecutionModeError(
            f"run_sim_loop requires CSM_EXECUTION_MODE='sim', got "
            f"{settings.execution_mode!r} ('off' disables execution; 'live' is not "
            f"implemented in Phase 5.1)"
        )

    instructions, skipped = build_order_instructions(trade_list, prices)
    book = portfolio if portfolio is not None else SimPortfolio()
    owns_adapter = adapter is None
    engine = adapter if adapter is not None else _build_adapter(settings)

    trackers: dict[str, _OrderTracker] = {}
    orders: list[NormalizedOrder] = []
    for instruction in instructions:
        cid = str(uuid.uuid4())
        trackers[cid] = _OrderTracker(instruction=instruction)
        orders.append(
            NormalizedOrder(
                client_order_id=cid,
                broker="sim",
                account=settings.execution_account or "",
                symbol=instruction.symbol,
                side=instruction.side,
                order_type="LIMIT",
                price=instruction.limit_price,
                quantity=instruction.quantity,
                tif="DAY",
            )
        )

    degraded = _Flag()
    connected = asyncio.Event()

    async def _run() -> None:
        async with asyncio.TaskGroup() as tg:
            stream_task = tg.create_task(
                _consume_stream(engine, trackers, book, degraded, connected)
            )
            try:
                await asyncio.wait_for(connected.wait(), timeout=stream_connect_timeout_seconds)
            except TimeoutError:
                logger.warning(
                    "stream not connected after %.1fs — submitting anyway "
                    "(GET-residual reconcile still guarantees correctness)",
                    stream_connect_timeout_seconds,
                )
            for order in orders:
                cid = order.client_order_id
                try:
                    await engine.submit_order(order)
                except OrderRejectedError as exc:
                    logger.warning("order rejected cid=%s code=%s: %s", cid, exc.code, exc.message)
                    tracker = trackers[cid]
                    tracker.final_state = "REJECTED"
                    tracker.reject = exc
                    tracker.done.set()
                # The ack never moves positions — fills arrive only via the stream.
            await _await_all_terminal(engine, trackers, book, degraded, order_timeout_seconds)
            stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stream_task

    if owns_adapter:
        async with engine:
            await _run()
    else:
        await _run()

    outcomes = [_build_outcome(cid, tracker) for cid, tracker in trackers.items()]
    return SimLoopResult(portfolio=book, outcomes=outcomes, skipped_symbols=skipped)


class _Flag:
    """A tiny mutable boolean shared across tasks (degraded-stream signal)."""

    __slots__ = ("value",)

    def __init__(self) -> None:
        self.value: bool = False


async def _consume_stream(
    engine: ExecutionEngineAdapter,
    trackers: dict[str, _OrderTracker],
    book: SimPortfolio,
    degraded: _Flag,
    connected: asyncio.Event,
) -> None:
    """Apply fill events to known orders; mark degraded and return on a stream reset."""
    try:
        async for event in engine.stream_updates(connected=connected):
            tracker = trackers.get(event.client_order_id)
            if tracker is None:
                continue  # not one of ours
            _apply_event(event, tracker, book)
    except StreamResetError as exc:
        logger.warning("stream reset (after_seq=%d) — degrading to GET polling", exc.after_seq)
        degraded.value = True


def _apply_event(event: OrderUpdateEvent, tracker: _OrderTracker, book: SimPortfolio) -> None:
    """Apply one order-update event's fill and terminal state to a tracker.

    ``avg_fill_price`` is the quantity-weighted average of the *applied fills*
    (``applied_cost / applied_qty``) — never the event's top-level ``price``
    field, which on the wire is the replace/amend price, not an average.
    """
    if event.fill is not None:
        book.apply_fill(
            tracker.instruction.symbol,
            tracker.instruction.side,
            event.fill.quantity,
            event.fill.price,
        )
        tracker.applied_qty += event.fill.quantity
        tracker.applied_cost += event.fill.price * event.fill.quantity
    if event.is_terminal:
        tracker.final_state = event.engine_state
        if tracker.applied_qty > 0:
            tracker.avg_fill_price = tracker.applied_cost / tracker.applied_qty
        tracker.done.set()


async def _await_all_terminal(
    engine: ExecutionEngineAdapter,
    trackers: dict[str, _OrderTracker],
    book: SimPortfolio,
    degraded: _Flag,
    order_timeout_seconds: float,
) -> None:
    """Wait for every order to terminate; reconcile via GET on timeout / degraded stream."""
    for cid, tracker in trackers.items():
        if tracker.done.is_set():
            continue
        if not degraded.value:
            try:
                async with asyncio.timeout(order_timeout_seconds):
                    await tracker.done.wait()
                continue
            except TimeoutError:
                logger.warning("order cid=%s timed out after %.1fs", cid, order_timeout_seconds)
        await _reconcile_via_get(engine, cid, tracker, book)


async def _reconcile_via_get(
    engine: ExecutionEngineAdapter,
    cid: str,
    tracker: _OrderTracker,
    book: SimPortfolio,
) -> None:
    """GET the order and apply the residual (filled_qty − applied_qty) if terminal."""
    result = await engine.get_order(cid)
    if result.is_terminal:
        residual = result.filled_qty - tracker.applied_qty
        if residual > 0 and result.avg_fill_price is not None:
            book.apply_fill(
                tracker.instruction.symbol,
                tracker.instruction.side,
                residual,
                result.avg_fill_price,
            )
            tracker.applied_qty += residual
            tracker.applied_cost += result.avg_fill_price * residual
        tracker.final_state = result.engine_state
        if result.avg_fill_price is not None:
            # Engine truth preferred over the locally-accumulated average.
            tracker.avg_fill_price = result.avg_fill_price
        tracker.done.set()
    else:
        logger.warning(
            "order cid=%s still non-terminal after GET (state=%s) — recording timeout",
            cid,
            result.engine_state,
        )
        tracker.final_state = None


def _build_outcome(cid: str, tracker: _OrderTracker) -> OrderOutcome:
    """Materialize an OrderOutcome from a tracker's final state."""
    if tracker.reject is not None:
        return OrderOutcome(
            instruction=tracker.instruction,
            client_order_id=cid,
            final_state="REJECTED",
            filled_qty=tracker.applied_qty,
            avg_fill_price=tracker.avg_fill_price,
            rejected=True,
            reject_code=tracker.reject.code,
            reject_message=tracker.reject.message,
        )
    return OrderOutcome(
        instruction=tracker.instruction,
        client_order_id=cid,
        final_state=tracker.final_state,
        filled_qty=tracker.applied_qty,
        avg_fill_price=tracker.avg_fill_price,
    )


__all__: list[str] = [
    "DEFAULT_ORDER_TIMEOUT_SECONDS",
    "DEFAULT_STREAM_CONNECT_TIMEOUT_SECONDS",
    "OrderOutcome",
    "SimLoopResult",
    "build_order_instructions",
    "run_sim_loop",
]
