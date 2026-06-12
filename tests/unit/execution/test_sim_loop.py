"""Unit tests for :mod:`csm.execution.sim_loop` (Phase 5.1 end-to-end loop)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pandas as pd
import pytest

from csm.config.settings import Settings
from csm.execution.engine_adapter import ExecutionEngineAdapter
from csm.execution.errors import ExecutionModeError, SimLoopError
from csm.execution.models import SimPortfolio, SimPosition
from csm.execution.sim_loop import build_order_instructions, run_sim_loop
from csm.execution.trade_list import Trade, TradeList, TradeSide

_TS = datetime(2026, 6, 12, 9, 0, tzinfo=UTC).isoformat()
# Engine-true mapping (quant-execution-engine ``to_public_status``).
_PUBLIC_STATUS = {
    "NEW": "NEW",
    "PARTIALLY_FILLED": "PARTIALLY_FILLED",
    "FILLED": "FILLED",
    "REJECTED": "REJECTED",
}


def _sim_settings() -> Settings:
    return Settings(
        execution_mode="sim",
        execution_account="SIM-1",
        gateway_base_url="http://gateway.test",
        gateway_api_key="key",  # type: ignore[arg-type]
        ohlcv_source="parquet",  # avoid the db engine-url model validator
    )


def _trade(symbol: str, side: TradeSide, delta: int) -> Trade:
    return Trade(
        symbol=symbol,
        side=side,
        target_weight=0.0,
        current_weight=0.0,
        delta_weight=0.0,
        target_shares=max(delta, 0),
        delta_shares=delta,
        notional_thb=0.0,
        expected_slippage_bps=0.0,
        participation_rate=0.0,
    )


def _trade_list(*trades: Trade) -> TradeList:
    return TradeList(trades=list(trades), asof=pd.Timestamp("2026-06-12", tz="Asia/Bangkok"))


def _result_body(
    cid: str, symbol: str, side: str, qty: int, state: str = "FILLED"
) -> dict[str, Any]:
    return {
        "client_order_id": cid,
        "broker": "sim",
        "status": _PUBLIC_STATUS[state],
        "engine_state": state,
        "filled_qty": qty if state in ("FILLED", "PARTIALLY_FILLED") else 0,
        "remaining_qty": 0 if state == "FILLED" else qty,
        "avg_fill_price": "35.55",
        "created_at": _TS,
        "updated_at": _TS,
    }


# --- A stateful fake engine over httpx.MockTransport -------------------------


class _StreamBody(httpx.AsyncByteStream):
    """Yields SSE frames from a shared queue until a sentinel ``None`` is enqueued."""

    def __init__(self, queue: asyncio.Queue[bytes | None]) -> None:
        self._queue = queue

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while True:
            chunk = await self._queue.get()
            if chunk is None:
                return
            yield chunk

    async def aclose(self) -> None:
        return None


class _FakeEngine:
    """Records submitted orders; serves POST/GET/stream with scripted fills.

    ``fill_plan`` maps a symbol to a list of (engine_state, fill_qty) or
    (engine_state, fill_qty, fill_price) event steps. The stream task emits
    those events for each submitted order, by client_order_id.
    """

    def __init__(
        self,
        *,
        fill_plan: dict[str, list[tuple[str, int] | tuple[str, int, str]]],
        post_status: int = 201,
        reject_symbols: dict[str, dict[str, Any]] | None = None,
        get_filled_qty: int | None = None,
        ack_state: dict[str, str] | None = None,
    ) -> None:
        self._fill_plan = fill_plan
        self._post_status = post_status
        self._reject_symbols = reject_symbols or {}
        self._get_filled_qty = get_filled_qty
        self._ack_state = ack_state or {}
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.submitted: list[dict[str, Any]] = []
        self.requests: list[httpx.Request] = []
        self._seq = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/orders/stream"):
            return httpx.Response(
                200,
                stream=_StreamBody(self.queue),
                headers={"content-type": "text/event-stream"},
            )
        if request.method == "POST" and path.endswith("/orders"):
            return self._handle_post(request)
        if request.method == "GET":
            return self._handle_get(path)
        raise AssertionError(f"unexpected request {request.method} {path}")

    def _handle_post(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.submitted.append(body)
        symbol = body["symbol"]
        cid = body["client_order_id"]
        if symbol in self._reject_symbols:
            return httpx.Response(422, json={"error": self._reject_symbols[symbol]})
        # Enqueue scripted stream events for this order.
        for step in self._fill_plan.get(symbol, [("FILLED", body["quantity"])]):
            state, fill_qty = step[0], step[1]
            fill_price = step[2] if len(step) == 3 else "35.55"
            self._enqueue_event(cid, symbol, body["side"], state, fill_qty, fill_price)
        ack = self._ack_state.get(symbol, "PENDING_NEW")
        return httpx.Response(
            self._post_status,
            json=_result_body(cid, symbol, body["side"], body["quantity"], ack)
            if ack in _PUBLIC_STATUS
            else _result_body_pending(cid, symbol),
        )

    def _handle_get(self, path: str) -> httpx.Response:
        cid = path.rsplit("/", 1)[-1]
        if self._get_filled_qty is not None:
            return httpx.Response(
                200,
                json={
                    "client_order_id": cid,
                    "broker": "sim",
                    "status": "FILLED",
                    "engine_state": "FILLED",
                    "filled_qty": self._get_filled_qty,
                    "remaining_qty": 0,
                    "avg_fill_price": "35.55",
                    "created_at": _TS,
                    "updated_at": _TS,
                },
            )
        return httpx.Response(404, json={"error": {"code": "not_found", "message": "x"}})

    def _enqueue_event(
        self,
        cid: str,
        symbol: str,
        side: str,
        state: str,
        fill_qty: int,
        fill_price: str = "35.55",
    ) -> None:
        self._seq += 1
        data: dict[str, Any] = {
            "seq": self._seq,
            "client_order_id": cid,
            "strategy_id": "csm-set",
            "engine_state": state,
            "status": _PUBLIC_STATUS[state],
            "price": "35.55",  # wire ``price`` = replace/amend price, NOT an average
            "ts": _TS,
        }
        if fill_qty > 0:
            data["fill"] = {
                "broker_fill_id": f"F-{self._seq}",
                "price": fill_price,
                "quantity": fill_qty,
                "exec_ts": _TS,
            }
        frame = f"id: {self._seq}\nevent: {state}\ndata: {json.dumps(data)}\n\n"
        self.queue.put_nowait(frame.encode())

    def enqueue_raw(self, frame: str) -> None:
        self.queue.put_nowait(frame.encode())

    def adapter(self) -> ExecutionEngineAdapter:
        return ExecutionEngineAdapter(
            base_url="http://gateway.test",
            api_key="key",
            transport=httpx.MockTransport(self.handler),
            backoff_seconds=(0.0,),
        )


def _result_body_pending(cid: str, symbol: str) -> dict[str, Any]:
    # A fresh ack is engine-true: status="NEW" with engine_state="PENDING_NEW".
    return {
        "client_order_id": cid,
        "broker": "sim",
        "status": "NEW",
        "engine_state": "PENDING_NEW",
        "filled_qty": 0,
        "remaining_qty": 0,
        "avg_fill_price": None,
        "created_at": _TS,
        "updated_at": _TS,
    }


# --- build_order_instructions -----------------------------------------------


class TestBuildInstructions:
    def test_skips_hold_and_zero_delta(self) -> None:
        tl = _trade_list(
            _trade("PTT", TradeSide.BUY, 100),
            _trade("CPN", TradeSide.HOLD, 0),
            _trade("SCB", TradeSide.BUY, 0),
        )
        ins, skipped = build_order_instructions(tl, {"PTT": Decimal("35.5")})
        assert len(ins) == 1
        assert ins[0].side == "BUY"
        assert sorted(skipped) == ["CPN", "SCB"]

    def test_sell_side_from_negative_delta(self) -> None:
        tl = _trade_list(_trade("PTT", TradeSide.SELL, -50))
        ins, _ = build_order_instructions(tl, {"PTT": Decimal("35.5")})
        assert ins[0].side == "SELL"
        assert ins[0].quantity == 50

    def test_missing_price_raises(self) -> None:
        tl = _trade_list(_trade("PTT", TradeSide.BUY, 100))
        with pytest.raises(SimLoopError, match="no price"):
            build_order_instructions(tl, {})


# --- run_sim_loop ------------------------------------------------------------


class TestRunSimLoop:
    @pytest.mark.asyncio
    async def test_mode_off_raises(self) -> None:
        settings = Settings(execution_mode="off", ohlcv_source="parquet")
        with pytest.raises(ExecutionModeError):
            await run_sim_loop(
                _trade_list(_trade("PTT", TradeSide.BUY, 100)),
                {"PTT": Decimal("35.5")},
                settings=settings,
            )

    @pytest.mark.asyncio
    async def test_happy_two_orders_buy_sell(self) -> None:
        fake = _FakeEngine(fill_plan={"PTT": [("FILLED", 100)], "SCB": [("FILLED", 50)]})
        portfolio = SimPortfolio(
            positions={"SCB": SimPosition(symbol="SCB", quantity=200, avg_price=Decimal("10"))}
        )
        tl = _trade_list(
            _trade("PTT", TradeSide.BUY, 100),
            _trade("SCB", TradeSide.SELL, -50),
        )
        result = await run_sim_loop(
            tl,
            {"PTT": Decimal("35.5"), "SCB": Decimal("12")},
            settings=_sim_settings(),
            portfolio=portfolio,
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        assert result.portfolio.positions["PTT"].quantity == 100
        assert result.portfolio.positions["SCB"].quantity == 150
        assert all(o.final_state == "FILLED" for o in result.outcomes)
        # distinct uuid4 client_order_ids
        cids = {o.client_order_id for o in result.outcomes}
        assert len(cids) == 2
        for cid in cids:
            import uuid

            assert uuid.UUID(cid).version == 4

    @pytest.mark.asyncio
    async def test_ack_already_filled_no_double_count(self) -> None:
        # The POST ack returns FILLED AND the stream replays the fill — apply once.
        fake = _FakeEngine(
            fill_plan={"PTT": [("FILLED", 100)]},
            ack_state={"PTT": "FILLED"},
        )
        tl = _trade_list(_trade("PTT", TradeSide.BUY, 100))
        result = await run_sim_loop(
            tl,
            {"PTT": Decimal("35.5")},
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        assert result.portfolio.positions["PTT"].quantity == 100  # exactly once

    @pytest.mark.asyncio
    async def test_partial_fills_aggregate(self) -> None:
        fake = _FakeEngine(fill_plan={"PTT": [("PARTIALLY_FILLED", 40), ("FILLED", 60)]})
        tl = _trade_list(_trade("PTT", TradeSide.BUY, 100))
        result = await run_sim_loop(
            tl,
            {"PTT": Decimal("35.5")},
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        assert result.portfolio.positions["PTT"].quantity == 100
        assert result.outcomes[0].final_state == "FILLED"

    @pytest.mark.asyncio
    async def test_reject_mid_batch_continues(self) -> None:
        fake = _FakeEngine(
            fill_plan={"PTT": [("FILLED", 100)], "SCB": [("FILLED", 50)]},
            reject_symbols={
                "CPN": {"code": "risk_rejected", "message": "cap", "client_order_id": "x"}
            },
        )
        tl = _trade_list(
            _trade("PTT", TradeSide.BUY, 100),
            _trade("CPN", TradeSide.BUY, 70),
            _trade("SCB", TradeSide.BUY, 50),
        )
        result = await run_sim_loop(
            tl,
            {"PTT": Decimal("35.5"), "CPN": Decimal("50"), "SCB": Decimal("12")},
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        by_symbol = {o.instruction.symbol: o for o in result.outcomes}
        assert by_symbol["PTT"].final_state == "FILLED"
        assert by_symbol["SCB"].final_state == "FILLED"
        assert by_symbol["CPN"].rejected is True
        assert by_symbol["CPN"].reject_code == "risk_rejected"
        assert result.portfolio.positions["PTT"].quantity == 100
        assert "CPN" not in result.portfolio.positions

    @pytest.mark.asyncio
    async def test_timeout_then_get_residual(self) -> None:
        # Stream delivers only 50/100 (no terminal); GET says 100 → apply +50 residual only.
        fake = _FakeEngine(
            fill_plan={"PTT": [("PARTIALLY_FILLED", 50)]},
            get_filled_qty=100,
        )
        tl = _trade_list(_trade("PTT", TradeSide.BUY, 100))
        result = await run_sim_loop(
            tl,
            {"PTT": Decimal("35.5")},
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=0.2,
        )
        assert result.portfolio.positions["PTT"].quantity == 100  # 50 stream + 50 residual
        assert result.outcomes[0].final_state == "FILLED"
        assert result.outcomes[0].filled_qty == 100

    @pytest.mark.asyncio
    async def test_stream_resync_degrades_to_get(self) -> None:
        # The stream emits resync_required before any fill; loop degrades to GET polling.
        fake = _FakeEngine(fill_plan={"PTT": []}, get_filled_qty=100)
        # Override: enqueue a resync advisory instead of fills when PTT is submitted.
        fake.enqueue_raw('event: resync_required\ndata: {"after_seq": 0}\n\n')
        tl = _trade_list(_trade("PTT", TradeSide.BUY, 100))
        result = await run_sim_loop(
            tl,
            {"PTT": Decimal("35.5")},
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        assert result.portfolio.positions["PTT"].quantity == 100  # via GET residual
        assert result.outcomes[0].final_state == "FILLED"

    @pytest.mark.asyncio
    async def test_distinct_uuids_per_order(self) -> None:
        fake = _FakeEngine(
            fill_plan={"PTT": [("FILLED", 100)], "SCB": [("FILLED", 50)], "CPN": [("FILLED", 10)]}
        )
        tl = _trade_list(
            _trade("PTT", TradeSide.BUY, 100),
            _trade("SCB", TradeSide.BUY, 50),
            _trade("CPN", TradeSide.BUY, 10),
        )
        await run_sim_loop(
            tl,
            {"PTT": Decimal("35.5"), "SCB": Decimal("12"), "CPN": Decimal("5")},
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        cids = [b["client_order_id"] for b in fake.submitted]
        assert len(cids) == len(set(cids)) == 3

    @pytest.mark.asyncio
    async def test_stream_subscribed_before_first_submit(self) -> None:
        # The connect handshake guarantees the stream GET reaches the transport
        # before the first POST — a synchronous sim fill must not be able to win
        # the race against a cursor-0 live-only stream.
        fake = _FakeEngine(fill_plan={"PTT": [("FILLED", 100)]})
        tl = _trade_list(_trade("PTT", TradeSide.BUY, 100))
        await run_sim_loop(
            tl,
            {"PTT": Decimal("35.5")},
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        assert fake.requests, "no requests recorded"
        assert fake.requests[0].url.path.endswith("/orders/stream")
        post_indices = [i for i, r in enumerate(fake.requests) if r.method == "POST"]
        assert post_indices and min(post_indices) >= 1  # every POST after the stream open

    @pytest.mark.asyncio
    async def test_stream_never_connects_warns_and_proceeds(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # The stream connect hangs forever; the loop must log a WARNING after the
        # bounded handshake wait and still complete via the GET-residual path.
        fake = _FakeEngine(fill_plan={"PTT": []}, get_filled_qty=100)

        async def hanging_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/orders/stream"):
                await asyncio.sleep(60.0)  # cancelled at loop teardown
            return fake.handler(request)

        adapter = ExecutionEngineAdapter(
            base_url="http://gateway.test",
            api_key="key",
            transport=httpx.MockTransport(hanging_handler),
            backoff_seconds=(0.0,),
        )
        with caplog.at_level(logging.WARNING, logger="csm.execution.sim_loop"):
            result = await run_sim_loop(
                _trade_list(_trade("PTT", TradeSide.BUY, 100)),
                {"PTT": Decimal("35.5")},
                settings=_sim_settings(),
                adapter=adapter,
                order_timeout_seconds=0.2,
                stream_connect_timeout_seconds=0.1,
            )
        assert "stream not connected" in caplog.text
        assert result.outcomes[0].final_state == "FILLED"
        assert result.portfolio.positions["PTT"].quantity == 100  # via GET reconcile

    @pytest.mark.asyncio
    async def test_avg_fill_price_weighted_across_partials(self) -> None:
        # 40 @ 35.00 + 60 @ 36.00 → 35.60. The event's top-level ``price``
        # (35.55, the replace/amend price) must NOT become the average.
        fake = _FakeEngine(
            fill_plan={"PTT": [("PARTIALLY_FILLED", 40, "35.00"), ("FILLED", 60, "36.00")]}
        )
        tl = _trade_list(_trade("PTT", TradeSide.BUY, 100))
        result = await run_sim_loop(
            tl,
            {"PTT": Decimal("35.5")},
            settings=_sim_settings(),
            adapter=fake.adapter(),
            order_timeout_seconds=5.0,
        )
        assert result.outcomes[0].filled_qty == 100
        assert result.outcomes[0].avg_fill_price == Decimal("35.60")

    @pytest.mark.asyncio
    async def test_timeout_still_non_terminal_records_none(self) -> None:
        # Stream delivers a partial but no terminal; GET also returns non-terminal →
        # the order records final_state=None and the loop completes without crashing.
        fake = _FakeEngine(fill_plan={"PTT": [("PARTIALLY_FILLED", 30)]})

        # GET returns a non-terminal (PARTIALLY_FILLED) body for any cid.
        def get_handler(request: httpx.Request) -> httpx.Response:
            fake.requests.append(request)
            path = request.url.path
            if path.endswith("/orders/stream"):
                return httpx.Response(
                    200,
                    stream=_StreamBody(fake.queue),
                    headers={"content-type": "text/event-stream"},
                )
            if request.method == "POST":
                return fake._handle_post(request)
            cid = path.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                json={
                    "client_order_id": cid,
                    "broker": "sim",
                    "status": "PARTIALLY_FILLED",
                    "engine_state": "PARTIALLY_FILLED",
                    "filled_qty": 30,
                    "remaining_qty": 70,
                    "avg_fill_price": "35.55",
                    "created_at": _TS,
                    "updated_at": _TS,
                },
            )

        adapter = ExecutionEngineAdapter(
            base_url="http://gateway.test",
            api_key="key",
            transport=httpx.MockTransport(get_handler),
            backoff_seconds=(0.0,),
        )
        result = await run_sim_loop(
            _trade_list(_trade("PTT", TradeSide.BUY, 100)),
            {"PTT": Decimal("35.5")},
            settings=_sim_settings(),
            adapter=adapter,
            order_timeout_seconds=0.2,
        )
        assert result.outcomes[0].final_state is None
        assert result.portfolio.positions["PTT"].quantity == 30  # only the streamed partial


class TestBuildAdapterGuards:
    @pytest.mark.asyncio
    async def test_missing_gateway_url_raises_mode_error(self) -> None:
        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            execution_mode="off",  # bypass settings validation, then force the path
            ohlcv_source="parquet",
        )
        forced = settings.model_copy(update={"execution_mode": "sim", "gateway_base_url": None})
        with pytest.raises(ExecutionModeError, match="CSM_GATEWAY_BASE_URL"):
            await run_sim_loop(
                _trade_list(_trade("PTT", TradeSide.BUY, 100)),
                {"PTT": Decimal("35.5")},
                settings=forced,
            )

    @pytest.mark.asyncio
    async def test_missing_gateway_key_raises_mode_error(self) -> None:
        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            execution_mode="off",
            ohlcv_source="parquet",
        )
        forced = settings.model_copy(
            update={
                "execution_mode": "sim",
                "gateway_base_url": "http://gateway.test",
                "gateway_api_key": None,
                "execution_account": "SIM-1",
            }
        )
        with pytest.raises(ExecutionModeError, match="CSM_GATEWAY_API_KEY"):
            await run_sim_loop(
                _trade_list(_trade("PTT", TradeSide.BUY, 100)),
                {"PTT": Decimal("35.5")},
                settings=forced,
            )
