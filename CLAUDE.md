# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`csm-set` is a Cross-Sectional Momentum strategy system for the Stock Exchange of Thailand (SET). It is a **headless Data Engine** — a FastAPI service on port 8000 that ships an embedded FastUI dashboard, a frontend-agnostic JSON contract under `results/static/`, and an optional write-back path into the shared `quant-infra-db` (Postgres + Mongo) stack.

The repo has two operating modes controlled by `CSM_PUBLIC_MODE`:

- **Public** (Docker default, `true`): read-only. Scheduler disabled, all write endpoints + `/api/v1/history/*` return 403, no credentials required.
- **Private** (`false`): owner mode. Scheduler runs (`CSM_REFRESH_CRON`, default 18:00 BKK Mon–Fri), data fetch and write endpoints are live, and — if `CSM_DB_WRITE_ENABLED=true` plus three DSNs — pipeline hooks mirror results to `quant-infra-db`.

## Commands

Everything runs through `uv`. Never call `python`/`pip`/`poetry`/`conda` directly.

```bash
uv sync --all-groups                                   # install deps (incl. dev + research)
uv run pytest tests/ -v                                # full unit + integration suite
uv run pytest tests/unit/features/test_momentum.py::test_name -v   # single test
uv run pytest --cov=src/csm --cov-report=term-missing  # with coverage (fail_under=90)
uv run pytest tests/integration/adapters/ -m infra_db  # marker-gated; needs live quant-infra-db
uv run ruff check .                                    # lint
uv run ruff format --check .                           # format check
uv run mypy src/                                       # strict type check on src/csm
uv run uvicorn api.main:app --reload --port 8000       # API dev server
uv run python ui/main.py                               # UI dev server
```

Combined quality gate (must pass before any commit):

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src/ && uv run pytest tests/ -v
```

Owner pipeline (private mode, requires `TVKIT_AUTH_TOKEN` for >5,000 bars/symbol):

```bash
uv run python scripts/fetch_history.py     # pull OHLCV via tvkit → data/raw
uv run python scripts/build_universe.py    # monthly universe snapshots → data/processed
uv run python scripts/export_results.py    # notebooks → HTML, backtest + signals → results/static
uv run python scripts/refresh_daily.py     # cron-equivalent daily refresh entrypoint
```

Docker:

```bash
docker compose up                                                       # public mode, port 8100
docker compose -f docker-compose.yml -f docker-compose.private.yml up   # owner mode (writable mounts + tvkit auth)
```

## Architecture

### Layering (one-way dependency)

```
src/csm/  →  api/  →  ui/
```

`src/csm/` is the library core and must NEVER import from `api/` or `ui/`. `api/` and `ui/` may import `src/csm/`. Tests mirror the source layout (`tests/unit/<subpkg>/` ↔ `src/csm/<subpkg>/`).

### Data flow

```
tvkit / settfex → src/csm/data       (fetch, normalize, persist Parquet partitioned by date)
                → src/csm/features   (momentum signals, sector features, feature pipeline)
                → src/csm/research   (cross-sectional ranking, IC, walk-forward backtest)
                → src/csm/portfolio  (weight construction: equal / vol-target / min-variance)
                → src/csm/risk       (Sharpe/Sortino/max-DD metrics, regime detection)
                → src/csm/execution  (trade-list generation, slippage)
                → src/csm/adapters   (write-back hooks: Postgres + Mongo + gateway)
                ↗
       api/ (FastAPI)  reads & exposes signals/backtest/portfolio/history/jobs/scheduler routers
       ui/  (FastUI)   mounted on FastAPI app
```

`src/csm/live/portfolio.py` writes live portfolio NAV to the **gateway** tables (`daily_performance`, `portfolio_snapshot`) via `csm.adapters.gateway` — not the synthetic backtest tables. This split is enforced (see commit `fb79f33`).

### FastAPI app composition (`api/main.py`)

Middleware stack (outermost first, since `add_middleware` is LIFO):

```
RequestIDMiddleware → AccessLogMiddleware → APIKeyMiddleware → public_mode_guard → CORSMiddleware → routers
```

- `public_mode_guard` blocks `WRITE_PATHS` (data refresh, backtest run, jobs, scheduler) and any path under `PRIVATE_ONLY_PREFIXES` (currently `/api/v1/history/`) with a `application/problem+json` 403 when `settings.public_mode` is true.
- `APIKeyMiddleware` enforces `X-API-Key` (constant-time compare) on protected endpoints when `CSM_API_KEY` is set. When unset, a startup WARNING is logged and protected endpoints are open.
- `AdapterManager` (in `app.state.adapters`) is constructed once in `lifespan` and owns the Postgres/Mongo/gateway pools. `await adapters.close()` and `scheduler.shutdown(wait=False)` run on shutdown.
- The APScheduler scheduler is created via `api.scheduler.jobs.create_scheduler` only in private mode; it owns the daily refresh job.

### OHLCV source (`CSM_OHLCV_SOURCE`)

The owner-side daily refresh acquires OHLCV through a small factory
(`csm.data.sources.build_ohlcv_loader`) selected by `CSM_OHLCV_SOURCE`:

- **`db`** (default): `MarketDataEngineLoader` reads pre-fetched bars from the **Market Data Engine**
  (`quant-marketdata-engine`, host `:8300`) over HTTP via
  `csm.adapters.market_data_engine_client`. csm-set holds **no tvkit cookie** on this path.
  Requires `CSM_MARKET_DATA_ENGINE_BASE_URL` (e.g. `http://quant-marketdata-engine:8000`
  in-cluster, `http://localhost:8300` for dev); `CSM_MARKET_DATA_ENGINE_API_KEY` is optional
  (only when the engine sets its own key).
- **`parquet`** (deprecated): the legacy path — `OHLCVLoader` fetches tvkit and
  persists the local Parquet store. Requires `TVKIT_AUTH_TOKEN`. Kept for rollback;
  triggers a `DeprecationWarning` on use.

Both loaders return the identical DataFrame shape (`open/high/low/close/volume` floats,
`Asia/Bangkok` `datetime` index), so downstream logic is source-agnostic. The default
was flipped from `parquet` to `db` in Phase 5 (2026-06-02) after 100% parity was
verified across 691 symbols. Rollback = set `CSM_OHLCV_SOURCE=parquet`. This is
Phase 5 of `feature-market-data-engine`.

### Execution mode (`CSM_EXECUTION_MODE`)

The optional execution path (feature-execution-engine Phase 5.1) is gated by
`CSM_EXECUTION_MODE`. It is a **library + verify-script only** facility — it is
**not** wired into the daily refresh or the scheduler; nothing routes an order
unless you call `csm.execution.run_sim_loop` (or the verify script) explicitly.

- **`off`** (default): zero-code path. The engine adapter is never instantiated
  and no order HTTP is performed. Adds no required env.
- **`sim`**: submit `NormalizedOrder`s through the **gateway proxy**
  (`/api/v2/engines/execution/*`) to the Execution engine `SimAdapter`, then
  apply the SSE fill stream (`GET /orders/stream`) to a local `SimPortfolio`.
  Requires `CSM_GATEWAY_BASE_URL`, `CSM_GATEWAY_API_KEY` (both reused from the
  daily-report path), and `CSM_EXECUTION_ACCOUNT`.
- **`live`**: RESERVED. Rejected at `Settings()` when `CSM_PUBLIC_MODE=true`,
  and unimplemented in Phase 5.1 (`run_sim_loop` only runs `sim`). When enabled
  it would source the real venue from `CSM_EXECUTION_BROKER` (so `live` +
  `CSM_EXECUTION_BROKER=sim` is rejected).

Supporting env:

- `CSM_EXECUTION_ACCOUNT` — broker account stamped on every order
  (`NormalizedOrder.account` is mandatory); required when mode != `off`.
- `CSM_EXECUTION_BROKER` — `sim` (default) | `liberator` | `settrade`.

No broker credential ever lives in this repo — the Execution engine is the sole
order-routing-credential owner; csm-set only ever posts a normalized order
through the gateway. The loop is single-source (positions move only from stream
`fill` events, never from the POST ack), uses a fresh UUIDv4 `client_order_id`
per logical order (the same id is reused only on transport/5xx retries), a
client-side seq watermark for reconnect dedupe, and a `GET /orders/{cid}`
residual reconcile on timeout or stream reset.

Module locations: `src/csm/execution/models.py` (wire mirrors),
`engine_adapter.py` (HTTP/SSE client), `sim_loop.py` (the loop),
`errors.py` (typed exceptions). Manual end-to-end check:
`uv run python scripts/verify_execution_sim.py --symbol PTT --side BUY --qty 100 --price 35.50`
(needs `CSM_EXECUTION_MODE=sim` + the gateway env above). See
`.claude/knowledge/execution-mode.md`.

### Adapters and storage

- **Parquet (PyArrow)** is the durable store for all tabular data in `data/` (gitignored) and `results/static/` (tracked). Partition by date where feasible; set column dtypes explicitly on read.
- **No SQLite/Postgres in `src/csm/` core** — the Postgres/Mongo dependency lives entirely in `src/csm/adapters/` and is opt-in via `CSM_DB_WRITE_ENABLED`. When disabled, the adapters are not constructed and pipeline hooks are no-ops.
- Three DBs when write-back is on:
  - `db_csm_set` (Postgres): `equity_curve` (TimescaleDB hypertable), `trade_history`, `backtest_log`
  - `db_gateway` (Postgres): `daily_performance`, `portfolio_snapshot` (cross-strategy)
  - `csm_logs` (Mongo): `signal_snapshots`, `backtest_results`, `model_params`

### Public data boundary

Raw OHLCV columns (`open`, `high`, `low`, `close`, `volume`, `adj_close`) must NEVER appear in `results/static/` or any API response. This is enforced by `tests/integration/test_public_data_boundary_files.py` and `test_public_data_boundary_api.py`. The `data/` directory is gitignored; `OHLCVLoader` raises `DataAccessError` in public mode.

## Hard rules (from `.claude/knowledge/project-skill.md`)

1. **Always `uv run`** — never bare `python`/`pip`/`poetry`/`conda`.
2. **Async-first I/O** — all HTTP via `httpx.AsyncClient`. `requests` is forbidden in `src/csm/` (sync; blocks the event loop).
3. **Pydantic at boundaries** — function I/O between `src/csm/`, `api/`, `ui/` goes through Pydantic models, never raw dicts.
4. **Notebook markdown cells are Thai; code stays English.**
5. **`docs/plans/` is git-tracked** — do not gitignore it.
6. **SET symbols come from `settfex`** — legacy `thai-securities-data` is removed; do not reintroduce.
7. **Timezone is `Asia/Bangkok`** — financial timestamps are tz-aware `pandas.Timestamp` stored in UTC, displayed in `Asia/Bangkok`. Never mix tz-naive and tz-aware in one frame.
8. **No secrets in repo** — all config via env + `pydantic-settings` (single `Settings` object in `src/csm/config/settings.py`).

## Coding conventions worth knowing up front

- `from __future__ import annotations` at the top of every `src/csm/` module.
- Module-local exceptions in each subpackage's `errors.py`, all inheriting from `CsmError`. Never `raise Exception(...)` or `except Exception: pass`.
- `logger = logging.getLogger(__name__)` — never `print` in `src/csm/`. Use `%`-formatting (`logger.info("fetched %d rows", n)`), not f-strings, so level filtering saves work.
- File-size target ≤ 400 lines; functions ≤ ~50 lines.
- Coverage target ≥ 90% on `src/csm/adapters/` and `api/` (enforced by `--cov-fail-under=90` in `pyproject.toml`).
- Tests use `asyncio_mode = "auto"` and `--import-mode=importlib` (so test modules with identical basenames coexist across `tests/unit/` and `tests/integration/`).
- Integration tests requiring the live `quant-infra-db` stack are marked `@pytest.mark.infra_db` and self-skip when DSNs are unset — the default `uv run pytest tests/` invocation never touches the live stack.

## Commits

Follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`. Keep scope tight (`fix(adapters): ...`, `chore(skills): ...`).
