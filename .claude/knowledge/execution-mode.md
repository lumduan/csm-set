# Execution mode (`CSM_EXECUTION_MODE`) — csm-set

Strategy-side scope of `feature-execution-engine` **Phase 5.1**: an opt-in,
library-only sim trade loop. Signal → `NormalizedOrder` → `POST /orders` (via the
gateway proxy) → SSE fill events → local `SimPortfolio`. No broker code lives in
this repo; the Execution engine is the sole order-routing-credential owner.

## Environment variables

| Var | Default | Meaning |
| --- | --- | --- |
| `CSM_EXECUTION_MODE` | `off` | `off` \| `sim` \| `live`. |
| `CSM_EXECUTION_ACCOUNT` | — | Broker account stamped on `NormalizedOrder.account`. Required when mode != `off`. |
| `CSM_EXECUTION_BROKER` | `sim` | `sim` \| `liberator` \| `settrade`. `live` mode sources the venue from this. |
| `CSM_GATEWAY_BASE_URL` | — | Gateway base URL (reused from the daily-report path). Required when mode != `off`. |
| `CSM_GATEWAY_API_KEY` | — | `X-API-Key` for every order request (reused). Required when mode != `off`. |

Validation (`Settings._validate_execution_path`, `mode="after"`):

- `off` → always valid, adds no required env (module-level `Settings()` keeps working).
- mode != `off` → requires `CSM_GATEWAY_BASE_URL`, `CSM_GATEWAY_API_KEY`,
  `CSM_EXECUTION_ACCOUNT` (each with its own `CSM_`-prefixed error).
- `live` + `CSM_PUBLIC_MODE=true` → rejected (public mode is read-only).
- `live` + `CSM_EXECUTION_BROKER=sim` → rejected (live needs a real venue).

## Mode semantics

- **off** — zero-code path. The adapter is never instantiated; no HTTP at all.
- **sim** — `run_sim_loop` builds NormalizedOrders, POSTs them through the
  gateway to the engine `SimAdapter`, and applies the SSE fill stream. Default
  and only implemented mode in Phase 5.1.
- **live** — RESERVED. `run_sim_loop` raises `ExecutionModeError` for any mode
  other than `sim`. Settings already forbids `live` in public mode.

## Wire rules (local mirrors in `execution/models.py`)

- **Local Pydantic mirrors only** — never import from `quant-execution-engine`.
- **Decimal-as-string on the wire** — `WireDecimal = Annotated[Decimal,
  PlainSerializer(format(d, "f"))]`. No floats, no scientific notation. The
  engine rejects floats.
- **SET-only** — `market` is pinned to `"SET"` and `position_effect` is never
  declared. `wire_dump()` uses `model_dump(mode="json", exclude_none=True)` so
  null fields (and the absent `position_effect`) are omitted from the body.
- **UUIDv4 `client_order_id`** per logical order. The **same** id is reused on
  transport/5xx retries of one submission (at-least-once + engine dedupe — a
  fresh id on retry risks double execution). A retry after a terminal REJECT is a
  new logical order → new id.

## Adapter (`engine_adapter.py`)

- `submit_order`: 200/201 → result (200 = idempotent resend, identical handling).
  Any typed `{"error": {code, message, ...}}` envelope — including an enveloped
  503 like `kill_switch_engaged` — is **terminal** → `OrderRejectedError` with the
  original code/message (never retried). Bare 5xx (502/503/504, no envelope) and
  `httpx.HTTPError` → retry the same cid with backoff, then `EngineAdapterError`.
- `get_order`: same envelope handling; used for residual reconcile.
- `stream_updates`: hand-rolled SSE over `aiter_lines` inside
  `client.stream(...)`, `httpx.Timeout(t, read=None)` (keep-alives ~15 s).
  Default filters on `strategy_id` (`csm-set`). `event: resync_required` →
  `StreamResetError(after_seq)`; `event: gap` → log + continue; `:` comments
  ignored. Client-side seq watermark (skip `seq <= cursor`); reconnect sends
  `Last-Event-ID: <cursor>`. Stream-open typed envelope → `OrderRejectedError`
  (no reconnect); mid-stream drop / clean EOF → backoff + reconnect, exhausted →
  `StreamError`.

## Loop invariants (`sim_loop.py`)

- **Subscribe-before-submit** — the stream-consumer task starts before the first
  POST, inside one `asyncio.TaskGroup`.
- **Single-source fills** — positions move **only** from stream `fill` events;
  the POST ack never updates positions. This kills the ack-already-FILLED +
  replay double-count class (the engine `SimAdapter` can return a FILLED ack and
  also stream the fill).
- **Seq watermark** — the adapter dedupes reconnect replays so a replayed fill is
  never applied twice.
- **Residual reconcile** — on per-order timeout or a degraded (reset) stream,
  `GET /orders/{cid}` and apply only `filled_qty − applied_qty` at
  `avg_fill_price`. A still-non-terminal order records `final_state=None` and
  logs `OrderTimeoutError` context; the loop completes without crashing.
- **Reject mid-batch continues** — a rejected order is recorded and the remaining
  orders still submit.
- **HOLD / zero-delta skipped**; a traded symbol missing from `prices` → loud
  `SimLoopError`. csm-set is long-only: an oversell raises `SimLoopError`.

## Verify runbook

```bash
export CSM_EXECUTION_MODE=sim
export CSM_EXECUTION_ACCOUNT=SIM-1
export CSM_GATEWAY_BASE_URL=http://localhost:8080   # gateway host port
export CSM_GATEWAY_API_KEY=<shared internal key>
uv run python scripts/verify_execution_sim.py --symbol PTT --side BUY --qty 100 --price 35.50
```

Exit 0 only when the order reached FILLED and the resulting position matches.
The engine must be in owner-mode sim (`stage: sim, public_mode: false`) for the
POST to be accepted; public mode (`:8400` default) returns 403. The
consolidated live e2e runbook lives in the umbrella plan
(`now-i-have-lucky-toucan.md`, step 4).
