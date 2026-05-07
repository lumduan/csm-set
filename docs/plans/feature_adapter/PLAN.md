# csm-set-adapter — Master Plan

**Feature:** Database integration layer connecting csm-set to the quant-infra-db stack
**Branch:** `feature/csm-set-adapter`
**Created:** 2026-05-06
**Status:** Draft — awaiting Phase 1 implementation
**Depends on:** `quant-infra-db` Phase 1–5 complete (quant-postgres + quant-mongo running on `quant-network`, all schemas live)
**Positioning:** Integration layer — promotes csm-set's local file-based outputs into a centralised, queryable, multi-strategy-ready persistence tier without altering strategy semantics.

---

## Table of Contents

1. [Overview](#overview)
2. [Problem Statement](#problem-statement)
3. [Design Rationale](#design-rationale)
4. [Architecture](#architecture)
5. [Status Symbols](#status-symbols)
6. [Implementation Phases](#implementation-phases)
7. [Data Flow Map](#data-flow-map)
8. [Dependency Map](#dependency-map)
9. [Error Handling Strategy](#error-handling-strategy)
10. [Testing Strategy](#testing-strategy)
11. [Exit Criteria](#exit-criteria)
12. [Current Status](#current-status)
13. [Commit & PR Templates](#commit--pr-templates)

---

## Overview

### Purpose

`csm-set-adapter` is the integration layer that connects **csm-set** (the SET cross-sectional momentum strategy engine, currently in live-test on the `live-test` branch) to the **quant-infra-db** stack (PostgreSQL + TimescaleDB + MongoDB running on the shared `quant-network` Docker network). After this feature lands:

- Every daily refresh writes equity curve, signal snapshot, daily performance, and portfolio snapshot rows to the central DB.
- Every backtest run persists its config, summary metrics, and full result document.
- Every rebalance event records the resulting trade list.
- A private-mode REST surface exposes those time series so an external API Gateway / Dashboard can consume csm-set history without touching the local `data/` directory.
- DB outages do not crash csm-set — write-back is best-effort with structured warnings.

### Scope

Seven phases in dependency order:

| Phase | Deliverable | Purpose |
|---|---|---|
| 1 | Connection & Config | asyncpg + motor wired into `Settings`, Docker network, health check |
| 2 | PostgreSQL Adapter (`db_csm_set`) | equity_curve / trade_history / backtest_log write-back |
| 3 | MongoDB Adapter (`csm_logs`) | backtest_results / signal_snapshots / model_params write-back |
| 4 | Gateway Adapter (`db_gateway`) | daily_performance / portfolio_snapshot for cross-strategy aggregation |
| 5 | Pipeline Integration | AdapterManager + post-refresh / post-backtest / post-rebalance hooks |
| 6 | API History Endpoints | Private-mode `/api/v1/history/*` REST surface backed by the adapters |
| 7 | Testing & Hardening | `infra_db`-marked integration suite, ≥90% coverage, CI workflow |

**Out of scope:**

- Schema migrations on the DB side (owned by `quant-infra-db`)
- Multi-strategy aggregation logic (the `db_gateway.portfolio_snapshot.allocation` JSONB is shaped for it but only csm-set populates it for now)
- Read-side caching / pagination on history endpoints (single-strategy volumes do not require it yet)
- Live broker connectors (see Phase 4 of the strategy roadmap)

### Validated Inputs

- The `quant-infra-db` containers (`quant-postgres`, `quant-mongo`) are reachable via Docker DNS on the `quant-network` network.
- Schemas exist in `db_csm_set` (`equity_curve`, `trade_history`, `backtest_log`), `csm_logs` (`backtest_results`, `signal_snapshots`, `model_params`), and `db_gateway` (`daily_performance`, `portfolio_snapshot`).
- csm-set is uv-managed (Python ≥ 3.11), FastAPI-based, async-first, with existing settings via `pydantic-settings`.

---

## Problem Statement

csm-set today persists its outputs as Parquet files under `data/processed/` and JSON snapshots under `results/`. That works for a single-machine, single-strategy operator, but blocks four near-term needs:

1. **Cross-process consumers** — an API Gateway, a dashboard, or a future broker bridge cannot tail Parquet files efficiently and cannot join csm-set output with other strategies' output.
2. **Time-series history at scale** — equity curves and daily performance series want a hypertable, not a Parquet file rewritten daily.
3. **Audit / replay** — backtest config + metrics + full result documents need to be queryable by `run_id`, not searched by timestamp in a directory listing.
4. **Resilience** — losing the local volume currently means losing all history; pushing to a managed Postgres + Mongo means the local volume becomes a cache, not the source of truth.

Solving these by writing through to `quant-infra-db` after each pipeline event — without making csm-set hard-depend on the DB — is the goal of this feature.

---

## Design Rationale

### Adapter pattern over ORM

Each target store gets a thin async adapter (`PostgresAdapter`, `MongoAdapter`, `GatewayAdapter`) that owns its connection pool and exposes purpose-built methods (`write_equity_curve`, `write_signal_snapshot`, …). No SQLAlchemy or ORM. Reasons: (a) the schemas are owned by `quant-infra-db` and we should not re-declare them, (b) `asyncpg.executemany` + raw SQL is the simplest path to idempotent batch inserts on TimescaleDB, (c) `motor` already gives us native async Mongo with no extra layer.

### Write-back is opt-in and best-effort

`Settings.db_write_enabled` defaults to `False`. Adapters initialise only when the flag is true *and* the relevant DSN is configured. When a write fails, we `logger.warning` and continue — the strategy pipeline never crashes due to a DB outage. This matches csm-set's existing posture (Parquet writes are also best-effort with retries).

### Idempotency at the SQL level

Every Postgres write uses `ON CONFLICT (...) DO UPDATE` (or `DO NOTHING` where mutation is forbidden, e.g. `backtest_log.run_id`). Every Mongo write uses `update_one(..., upsert=True)` keyed on natural identifiers (`(strategy_id, date)`, `run_id`, `(strategy_id, version)`). Re-running daily refresh or replaying a backtest is therefore safe.

### Single coordination point: `AdapterManager`

The FastAPI lifespan owns one `AdapterManager` instance. It exposes `manager.postgres`, `manager.mongo`, `manager.gateway` — each `None` if disabled or unconfigured. Pipeline hooks always check `if manager.postgres:` before calling, so the same code paths work in DB-on and DB-off modes.

### REST surface mirrors store layout, not DB shape

History endpoints expose strategy-centric resources (`/api/v1/history/equity-curve`, `/api/v1/history/trades`, `/api/v1/history/performance`, …) and return Pydantic-validated payloads. Consumers never see raw SQL columns. This keeps the DB schema free to evolve under the adapter without breaking dashboards.

### Pydantic at every module boundary

All adapter inputs and outputs cross typed boundaries. DataFrames are accepted at `write_equity_curve` / `write_trade_history` (per the project-wide DataFrame exception for OHLCV-shaped data) but everything else — config dicts, document payloads, response schemas — is a Pydantic v2 model.

---

## Architecture

### Directory Layout

```
csm-set/
├── src/csm/
│   ├── adapters/                      # NEW package
│   │   ├── __init__.py                # AdapterManager
│   │   ├── health.py                  # check_db_connectivity()
│   │   ├── postgres.py                # PostgresAdapter (db_csm_set)
│   │   ├── mongo.py                   # MongoAdapter (csm_logs)
│   │   └── gateway.py                 # GatewayAdapter (db_gateway)
│   └── config/
│       └── settings.py                # MODIFIED — DSNs + db_write_enabled
│
├── api/
│   ├── main.py                        # MODIFIED — AdapterManager lifespan + health.db
│   └── routers/
│       └── history.py                 # NEW — /api/v1/history/* (private mode)
│
├── tests/
│   ├── unit/adapters/                 # NEW — pure unit tests with mocks
│   │   ├── test_postgres.py
│   │   ├── test_mongo.py
│   │   ├── test_gateway.py
│   │   └── test_manager.py
│   └── integration/adapters/          # NEW — marker: infra_db
│       ├── conftest.py                # shared fixtures + teardown
│       ├── test_postgres_io.py
│       ├── test_mongo_io.py
│       ├── test_gateway_io.py
│       └── test_pipeline.py           # end-to-end refresh → DB
│
├── docker-compose.yml                 # MODIFIED — join quant-network
├── docker-compose.private.yml         # MODIFIED — join quant-network
├── .env.example                       # MODIFIED — DB DSNs, db_write_enabled
├── pyproject.toml                     # MODIFIED — asyncpg, motor deps; coverage gate
└── .github/workflows/
    └── infra-integration.yml          # NEW — spins up quant-infra-db, runs infra_db tests
```

### Dependency Graph

```
Settings (csm.config)
    ↓
AdapterManager (csm.adapters.__init__)
    ├── PostgresAdapter (asyncpg pool)        — db_csm_set
    ├── MongoAdapter    (motor client)        — csm_logs
    └── GatewayAdapter  (asyncpg pool)        — db_gateway
    ↑
FastAPI lifespan (api.main)
    ├── /health (csm.adapters.health.check_db_connectivity)
    ├── /api/v1/history/* (api.routers.history)
    ├── post-refresh hook   (scheduler / scripts.export_results)
    ├── post-backtest hook  (api.routers.backtest)
    └── post-rebalance hook (rebalance workflow)
```

### Per-Event Write-back Flow

```
[Daily refresh complete]
    → equity_curve  → PostgresAdapter.write_equity_curve()         → db_csm_set.equity_curve
    → rankings      → MongoAdapter.write_signal_snapshot()         → csm_logs.signal_snapshots
    → metrics       → GatewayAdapter.write_daily_performance()     → db_gateway.daily_performance
    → snapshot      → GatewayAdapter.write_portfolio_snapshot()    → db_gateway.portfolio_snapshot

[Backtest job complete]
    → log entry     → PostgresAdapter.write_backtest_log()         → db_csm_set.backtest_log
    → result doc    → MongoAdapter.write_backtest_result()         → csm_logs.backtest_results
    → params        → MongoAdapter.write_model_params()            → csm_logs.model_params

[Rebalance complete]
    → trade list    → PostgresAdapter.write_trade_history()        → db_csm_set.trade_history
```

---

## Status Symbols

| Symbol | Meaning |
|---|---|
| `[ ]` | Not started |
| `[~]` | In progress |
| `[x]` | Complete |
| `[-]` | Skipped / deferred |

---

## Implementation Phases

### Phase 1 — Connection & Config

**Status:** `[x]` Complete — 2026-05-06
**Goal:** csm-set can reach `quant-postgres` and `quant-mongo` over `quant-network` and reports connectivity in `/health`. Write-back is wired through but disabled by default; graceful degradation on missing DSNs.

**Rationale:** Every later phase depends on a typed `Settings` surface, async client libraries (`asyncpg`, `motor`), and a Docker network in which the container actually resolves the DB hostnames. Doing this first unblocks all four adapters in parallel.

#### 1.1 Dependencies & Settings

- [x] Add to `[project].dependencies` in `pyproject.toml`:
  - `asyncpg>=0.29`
  - `motor>=3.4`
- [x] Extend `src/csm/config/settings.py` `Settings` with:
  ```python
  db_csm_set_dsn: str | None = None
  db_gateway_dsn: str | None = None
  mongo_uri: str | None = None
  db_write_enabled: bool = False
  ```
  All fields read from `CSM_*` env vars per the existing `env_prefix="CSM_"` config.
- [x] Update `.env.example`:
  ```env
  # quant-infra-db connections (required when CSM_DB_WRITE_ENABLED=true)
  CSM_DB_CSM_SET_DSN=postgresql://postgres:<pass>@quant-postgres:5432/db_csm_set
  CSM_DB_GATEWAY_DSN=postgresql://postgres:<pass>@quant-postgres:5432/db_gateway
  CSM_MONGO_URI=mongodb://quant-mongo:27017/
  CSM_DB_WRITE_ENABLED=false
  ```
- [x] Unit test in `tests/unit/config/test_settings.py`: confirm `db_write_enabled` defaults to `False` and that DSN fields parse correctly from env.

**Acceptance criteria:**
- [x] `uv run python -c "from csm.config.settings import settings; print(settings.db_write_enabled)"` prints `False` with no error.
- [x] `uv sync --all-groups` resolves cleanly with the new dependencies.
- [x] `uv run mypy src/csm/config/settings.py` is clean.

#### 1.2 Docker Compose — join `quant-network`

- [x] Patch `docker-compose.yml` so the `csm` service joins the externally-managed `quant-network`:
  ```yaml
  networks:
    default:
      name: quant-network
      external: true
  ```
- [x] Mirror the change in `docker-compose.private.yml`.
- [-] Update `README.md` "Running with Docker" section: prerequisites are (a) `quant-infra-db` stack up, (b) `docker network ls | grep quant-network` returns the network. *(Deferred — README update in Phase 7 per master plan.)*

**Acceptance criteria:**
- [~] `docker compose up -d csm` succeeds when `quant-network` exists. *(Requires quant-infra-db stack; tested via static validation.)*
- [~] `docker compose exec csm ping -c 1 quant-postgres` exits 0. *(Requires quant-infra-db stack.)*
- [~] `docker compose exec csm ping -c 1 quant-mongo` exits 0. *(Requires quant-infra-db stack.)*

#### 1.3 Adapter package skeleton + connectivity check

- [x] Create package `src/csm/adapters/` with empty `postgres.py`, `mongo.py`, `gateway.py` (filled in Phases 2–4) and an `__init__.py` exporting `AdapterManager` (filled in Phase 5).
- [x] Implement `src/csm/adapters/health.py`:
  ```python
  async def check_db_connectivity(settings: Settings) -> dict[str, str]:
      """Return {"postgres": "ok"|"error:<msg>", "mongo": "ok"|"error:<msg>"}."""
  ```
  Uses short-lived connections (no pool reuse) so it can run before lifespan startup.
- [x] Extend `api/schemas/health.py` `HealthStatus` with `db: dict[str, str] | None`.
- [x] Wire `check_db_connectivity` into the `/health` route in `api/main.py`.
- [x] Unit test `tests/unit/adapters/test_health.py`: mock both clients to raise; assert response is `{"postgres": "error:...", "mongo": "error:..."}`.
- [x] Integration test `tests/integration/adapters/test_health_io.py` (`@pytest.mark.infra_db`): assert `{"postgres": "ok", "mongo": "ok"}` against the real stack.

**Acceptance criteria:**
- [~] `curl http://localhost:8100/health` returns `"db": {"postgres": "ok", "mongo": "ok"}` when the stack is up, and `"db": null` when `db_write_enabled=False`. *(db=null path verified; live stack verification deferred.)*
- [x] `uv run pytest tests/unit/adapters/test_health.py -v` is green.

---

### Phase 2 — PostgreSQL Adapter (`db_csm_set`)

**Status:** `[x]` Complete — 2026-05-07
**Goal:** Idempotent async writes for `equity_curve`, `trade_history`, `backtest_log` using a single connection pool.

**Rationale:** `db_csm_set` is the strategy-private persistence tier. Getting it to feature-parity with the local Parquet output is the smallest unit of value the rest of the plan stacks on.

> **Scope notes (recorded 2026-05-07):** Phase 2 was extended with two user-approved deviations:
>
> - **Read methods pulled forward from Phase 6** — see §2.5. Phase 6 will only need to add routers + Pydantic response schemas; the SQL surface is owned here.
> - **`AdapterManager` skeleton + FastAPI lifespan wiring pulled forward from Phase 5.1** — see §2.6. Mongo/Gateway slots remain `None` until their phases.

#### 2.1 `PostgresAdapter` base

- [x] Implement `src/csm/adapters/postgres.py` `PostgresAdapter`:
  ```python
  class PostgresAdapter:
      def __init__(self, dsn: str) -> None: ...
      async def connect(self) -> None: ...      # asyncpg.create_pool(min=2, max=10)
      async def close(self) -> None: ...
      async def __aenter__(self) -> "PostgresAdapter": ...
      async def __aexit__(self, *exc) -> None: ...
      async def ping(self) -> bool: ...         # SELECT 1 through pool
  ```
- [x] Centralised SQL constants in a private `_SQL` namespace (no inline string concatenation).
- [x] JSONB type codec registered in pool `init` callback so dict ↔ JSONB round-trips automatically.
- [x] Unit test `tests/unit/adapters/test_postgres.py::TestLifecycle`: mocks `asyncpg.create_pool`; asserts `connect` and `close` are called once each, idempotency, `ping` behaviour, and `_require_pool` guard.

**Acceptance criteria:** `uv run mypy src/csm/adapters/postgres.py` is clean; `PostgresAdapter` can be instantiated without a live DB. ✅

#### 2.2 `write_equity_curve`

- [x] Method signature:
  ```python
  async def write_equity_curve(self, strategy_id: str, series: pd.Series) -> int:
      """Upsert (time, strategy_id, equity) rows. Returns row count written."""
  ```
- [x] Batched via `pool.executemany` — never one INSERT per row.
- [x] SQL: `INSERT ... ON CONFLICT (time, strategy_id) DO UPDATE SET equity = EXCLUDED.equity`.
- [x] Unit test: mock pool; assert `executemany` called once with N parameter tuples.
- [x] Integration test (`infra_db`): write 10 rows for `strategy_id='test-csm-set'`; rerun; `SELECT count(*)` returns 10 both times; autouse teardown removes rows.

**Acceptance criteria:** integration test green; rerunning the write produces the same row count (idempotent). ✅

#### 2.3 `write_trade_history`

- [x] Method signature:
  ```python
  async def write_trade_history(self, strategy_id: str, trades: pd.DataFrame) -> int:
      """Upsert trade rows. Columns: time, symbol, side, quantity, price, commission."""
  ```
- [x] Idempotent on `(strategy_id, time, symbol, side)` natural key.
- [x] Required-columns guard raises `KeyError` with descriptive message when input DataFrame is malformed.
- [x] Unit test: 3-row DataFrame produces 3 parameter tuples; missing-column case raises.
- [x] Integration test: write trades twice; row count remains 3.

**Acceptance criteria:** writing the same DataFrame twice does not duplicate rows. ✅

#### 2.4 `write_backtest_log`

- [x] Method signature:
  ```python
  async def write_backtest_log(
      self,
      run_id: str,
      strategy_id: str,
      config: dict[str, object],
      summary: dict[str, object],
  ) -> None:
      """Insert a single row. ON CONFLICT (run_id) DO NOTHING."""
  ```
- [x] `config` and `summary` serialised via `json.dumps` and inserted with explicit `$3::jsonb` / `$4::jsonb` casts. Phase 5 hook will pass `BacktestResult.metrics_dict()` as `summary`.
- [x] Unit test: assert `execute` called with JSON payloads and `ON CONFLICT (run_id) DO NOTHING` SQL.
- [x] Integration test: write same `run_id` twice with different summary; first-write summary preserved (DO NOTHING).

**Acceptance criteria:** `db_csm_set.backtest_log` carries metrics for every recent backtest. ✅

#### 2.5 Read methods (pulled forward from Phase 6)

- [x] `async def read_equity_curve(strategy_id: str, days: int = 90) -> list[EquityPoint]` — last `days` rows, ascending by time.
- [x] `async def read_trade_history(strategy_id: str, limit: int = 100) -> list[TradeRow]` — most recent `limit`, descending by time.
- [x] `async def read_backtest_log(strategy_id: str | None = None, limit: int = 50) -> list[BacktestLogRow]` — descending by `created_at`, optional strategy filter via `($1::text IS NULL OR strategy_id = $1)`.
- [x] Frozen Pydantic models in `src/csm/adapters/models.py` (`EquityPoint`, `TradeRow`, `BacktestLogRow`).
- [x] Unit tests: each read fetches dict rows and validates them into the model.
- [x] Integration tests: round-trip writes; ordering and limit honoured; JSONB returns as dict.

**Acceptance criteria:** Phase 6 routers can wrap these methods directly without touching SQL. ✅

#### 2.6 `AdapterManager` skeleton + lifespan wiring (pulled forward from Phase 5.1)

- [x] `AdapterManager` in `src/csm/adapters/__init__.py` exposes `postgres: PostgresAdapter | None` plus reserved `mongo`/`gateway` slots (typed as `object | None` until Phases 3–4).
- [x] `AdapterManager.from_settings(settings)` constructs the Postgres adapter when `db_write_enabled=True` *and* `db_csm_set_dsn` is set; missing DSN and `connect()` failures both downgrade to `postgres=None` with a logged warning. App boot never crashes.
- [x] `AdapterManager.close()` is best-effort — close failures are logged, not raised.
- [x] `AdapterManager.ping()` returns `{"postgres": "ok"|"error:..."}` per live adapter, empty dict otherwise.
- [x] FastAPI `lifespan` constructs the manager, stores it on `app.state.adapters`, and awaits `manager.close()` on shutdown.
- [x] `api/deps.py` exposes `get_adapter_manager(request)` paralleling `get_store()`.
- [x] `/health` merges `manager.ping()` into the existing short-lived `check_db_connectivity()` response so Phase 1 behaviour is preserved when `db_write_enabled=False` and the pool ping is preferred when the adapter is live.
- [x] Unit tests cover all degradation paths plus lifespan wiring (`tests/unit/adapters/test_manager.py`, `tests/unit/test_api_lifespan.py::TestAdapterManagerLifespan`).

**Acceptance criteria:** `app.state.adapters` is an `AdapterManager` after startup; pool is closed on shutdown; `/health` carries `db.postgres="ok"` when the live adapter is up. ✅

---

### Phase 3 — MongoDB Adapter (`csm_logs`)

**Status:** `[x]` Complete — 2026-05-07
**Goal:** Schema-less write-back for `backtest_results`, `signal_snapshots`, `model_params` via `motor`.

> **Scope note (recorded 2026-05-07):** Phase 3 was extended with one user-approved deviation:
>
> - **Read methods pulled forward from Phase 6** — in addition to the three writes, `MongoAdapter` ships `read_backtest_result`, `read_signal_snapshot`, `read_model_params`, and `list_backtest_results` plus frozen Pydantic models (`BacktestResultDoc`, `SignalSnapshotDoc`, `ModelParamsDoc`, `BacktestSummaryRow`). Phase 6 will only need to add routers + response schemas; the Mongo surface is owned here. Mirrors the Phase 2 precedent.

**Rationale:** Mongo is the right home for variable-shape documents (full backtest result payloads, ranking arrays, config snapshots). Keeping these out of Postgres avoids schema churn each time we add a metric.

#### 3.1 `MongoAdapter` base

- [x] Implement `src/csm/adapters/mongo.py`:
  ```python
  class MongoAdapter:
      def __init__(self, uri: str, db_name: str = "csm_logs") -> None: ...
      async def connect(self) -> None: ...      # motor.AsyncIOMotorClient
      async def close(self) -> None: ...
  ```
- [x] Unit test: instantiation does not raise; `connect` / `close` are idempotent.

**Acceptance criteria:** `uv run mypy src/csm/adapters/mongo.py` clean. ✅

#### 3.2 `write_backtest_result`

- [x] Method signature:
  ```python
  async def write_backtest_result(self, result_doc: dict[str, object]) -> None:
      """Upsert one document into csm_logs.backtest_results, keyed on run_id."""
  ```
- [x] Document shape: `{strategy_id, run_id, created_at, metrics, config, equity_curve, trades}`.
- [x] `replace_one({"run_id": ...}, doc, upsert=True)`.
- [x] Unit test: mock motor; assert filter uses `run_id`.
- [x] Integration test: insert; `find_one({"strategy_id": ...})` returns it.

#### 3.3 `write_signal_snapshot`

- [x] Method signature:
  ```python
  async def write_signal_snapshot(
      self,
      strategy_id: str,
      date: datetime,
      rankings: list[dict[str, object]],
  ) -> None:
      """Upsert keyed on (strategy_id, date)."""
  ```
- [x] Map `latest_ranking.json` (already produced by csm-set) → document.
- [x] Unit test: 20-symbol rankings produce a single document.
- [x] Integration test: write two consecutive days; query by `date` returns the right one.

#### 3.4 `write_model_params`

- [x] Method signature:
  ```python
  async def write_model_params(
      self,
      strategy_id: str,
      version: str,
      params: dict[str, object],
  ) -> None:
      """Upsert keyed on (strategy_id, version)."""
  ```
- [x] Captures the live config snapshot (formation period, top-quintile threshold, regime settings).
- [x] Integration test: write; `find_one({"version": ...})` returns the same params.

**Acceptance criteria:** `csm_logs` carries the config used for every live-test run. ✅

---

### Phase 4 — Gateway Adapter (`db_gateway`)

**Status:** `[x]` Complete — 2026-05-07
**Goal:** Cross-strategy aggregate persistence in `db_gateway` — `daily_performance` and `portfolio_snapshot`.

**Rationale:** The Gateway DB is the one a future API Gateway / multi-strategy dashboard reads. Even with one strategy today, populating it now means the dashboard contract is real, and the JSONB `allocation` column already shapes for multi-strategy.

> **Scope notes (recorded 2026-05-07):** Phase 4 was extended with one user-approved deviation:
>
> - **Read methods pulled forward from Phase 6** — in addition to the two writes, `GatewayAdapter` ships `read_daily_performance` and `read_portfolio_snapshots` plus frozen Pydantic models (`DailyPerformanceRow`, `PortfolioSnapshotRow`). Phase 6 will only need to add routers + response schemas; the SQL surface is owned here. Mirrors the Phase 2 and Phase 3 precedents.

#### 4.1 `GatewayAdapter` base

- [x] Implement `src/csm/adapters/gateway.py`:
  ```python
  class GatewayAdapter:
      def __init__(self, dsn: str) -> None: ...
      async def connect(self) -> None: ...
      async def close(self) -> None: ...
  ```
- [x] Pool sizing identical to `PostgresAdapter` (min=2, max=10). Reuses `_init_connection` JSONB codec from `postgres.py`.
- [x] Unit test: import + lifecycle.

#### 4.2 `write_daily_performance`

- [x] Method signature:
  ```python
  async def write_daily_performance(
      self,
      strategy_id: str,
      date: datetime,
      metrics: dict[str, object],
  ) -> None:
      """Upsert (time, strategy_id, daily_return, cumulative_return,
                 total_value, cash_balance, max_drawdown, sharpe_ratio, metadata)."""
  ```
- [x] Source from csm-set's existing `PerformanceMetrics` output.
- [x] `ON CONFLICT (time, strategy_id) DO UPDATE` for re-runs.
- [x] Integration test: write 30 days; read returns expected values.

#### 4.3 `write_portfolio_snapshot`

- [x] Method signature:
  ```python
  async def write_portfolio_snapshot(
      self,
      date: datetime,
      snapshot: dict[str, object],
  ) -> None:
      """Upsert (time, total_portfolio, weighted_return, combined_drawdown,
                 active_strategies, allocation::jsonb)."""
  ```
- [x] `allocation` is `{"csm-set": 1.0}` today, ready for multi-strategy without schema change.
- [x] Integration test: write two `(date, allocation)` tuples representing two strategies; aggregate query returns combined allocation.

#### 4.4 Read methods (pulled forward from Phase 6)

- [x] `async def read_daily_performance(strategy_id: str, days: int = 90) -> list[DailyPerformanceRow]` — last `days` rows, ascending by time.
- [x] `async def read_portfolio_snapshots(days: int = 90) -> list[PortfolioSnapshotRow]` — last `days` rows, ascending by time.
- [x] Frozen Pydantic models in `src/csm/adapters/models.py` (`DailyPerformanceRow`, `PortfolioSnapshotRow`).
- [x] Unit tests: each read fetches dict rows and validates them into the model.
- [x] Integration tests: round-trip writes; ordering and limit honoured; JSONB returns as dict.

**Acceptance criteria:** `db_gateway.portfolio_snapshot` is updated on every rebalance day. ✅

---

### Phase 5 — Pipeline Integration

**Status:** `[x]` Complete — 2026-05-07
**Goal:** Wire the adapters into csm-set's three event hooks (post-refresh, post-backtest, post-rebalance) so write-back is automatic. App boot stays correct in DB-on and DB-off modes.

**Rationale:** Phases 2–4 produce the machinery. This phase makes it actually fire from production code paths.

#### 5.1 `AdapterManager` (central coordinator)

> **Status:** Skeleton + Postgres slot delivered in Phase 2 (2026-05-07). Mongo slot delivered and typed `MongoAdapter | None` in Phase 3 (2026-05-07). Gateway slot delivered and typed `GatewayAdapter | None` in Phase 4 (2026-05-07). Pipeline-hook items 5.2–5.4 below remain pending.

- [x] Implement `AdapterManager` in `src/csm/adapters/__init__.py` (Phase 2):
  ```python
  class AdapterManager:
      postgres: PostgresAdapter | None
      mongo: MongoAdapter | None       # filled in Phase 3
      gateway: GatewayAdapter | None   # filled in Phase 4

      @classmethod
      async def from_settings(cls, settings: Settings) -> "AdapterManager":
          """Construct adapters only when db_write_enabled=True AND DSN is set.
          Missing DSN → adapter=None, log warning, do not raise."""

      async def close(self) -> None: ...
      async def ping(self) -> dict[str, str]: ...
  ```
- [x] Wire into `api/main.py` `lifespan` (Phase 2):
  - Create on startup; store on `app.state.adapters`.
  - Close on shutdown.
- [x] Unit test: with `db_write_enabled=False`, all three attributes are `None` (Phase 2).
- [x] Unit test: with flag on but DSN missing, `manager.postgres is None` and a warning is logged (Phase 2 — Mongo/Gateway equivalents arrive with their phases).
- [x] Unit test: with flag on and Postgres DSN set, the Postgres adapter is initialised (Phase 2 — full multi-adapter happy path completes after Phase 4).

**Acceptance criteria:** `uv run uvicorn api.main:app --port 8000` boots cleanly in both modes. ✅ (verified for Postgres slot)

#### 5.2 Post-refresh hook (daily signal → DB)

- [x] After daily refresh succeeds (in `api/scheduler/jobs.py` or `scripts/export_results.py` — whichever owns that lifecycle today), call:
  ```python
  if mgr.postgres:  await mgr.postgres.write_equity_curve("csm-set", equity_series)
  if mgr.mongo:     await mgr.mongo.write_signal_snapshot("csm-set", today, rankings)
  if mgr.gateway:
      await mgr.gateway.write_daily_performance("csm-set", today, metrics)
      await mgr.gateway.write_portfolio_snapshot(today, snapshot)
  ```
- [x] Each call wrapped in `try/except` that logs `WARNING` and continues.
- [x] Integration test (`infra_db`): trigger refresh; assert the four target tables/collections each grew by exactly one row/document.

**Acceptance criteria:** A scheduled run produces rows in `equity_curve`, `signal_snapshots`, `daily_performance`, `portfolio_snapshot`; a forced DB outage produces a warning, not a crash. ✅

#### 5.3 Post-backtest hook (backtest → DB)

- [x] In `api/routers/backtest.py`, after a job moves to `SUCCESS`:
  ```python
  if mgr.postgres: await mgr.postgres.write_backtest_log(run_id, "csm-set", config, summary)
  if mgr.mongo:
      await mgr.mongo.write_backtest_result(result_doc)
      await mgr.mongo.write_model_params("csm-set", version, params)
  ```
- [x] Integration test: trigger `/api/v1/backtest/run`; assert one row in `backtest_log`, one document in `backtest_results`, one document in `model_params`.

**Acceptance criteria:** Every backtest run is queryable by `run_id` from both Postgres and Mongo. ✅

#### 5.4 Post-rebalance hook (trades → DB)

- [x] In the rebalance workflow, after the trade list is generated:
  ```python
  if mgr.postgres: await mgr.postgres.write_trade_history("csm-set", trade_df)
  ```
- [x] Integration test: simulate rebalance; assert `trade_history` rows match the local DataFrame.

**Acceptance criteria:** `db_csm_set.trade_history` is updated on every rebalance event. ✅

---

### Phase 6 — API History Endpoints

**Status:** `[x]` Complete — 2026-05-07
**Goal:** Private-mode REST surface (`/api/v1/history/*`) backed by the adapters so external dashboards can query time series directly.

**Rationale:** csm-set already exposes today-snapshot endpoints. The DB makes time-series queries cheap, and a typed REST surface lets us evolve the schema independently of consumer code.

> **Status note:** The underlying adapter reads (`PostgresAdapter.read_equity_curve` / `read_trade_history` / `read_backtest_log`, `MongoAdapter.read_backtest_result` / `read_signal_snapshot` / `read_model_params` / `list_backtest_results`, `GatewayAdapter.read_daily_performance` / `read_portfolio_snapshots`) and all Pydantic models were delivered in Phases 2–4 (2026-05-07). Phase 6 only needs to add the routers, request validation, and response schemas on top.

#### 6.1 Equity curve & trade history

- [x] Create `api/routers/history.py` with router prefix `/api/v1/history`.
- [x] Endpoints:
  - `GET /equity-curve?strategy_id=csm-set&days=90` → `list[EquityPoint]` (model from `csm.adapters.models`)
  - `GET /trades?strategy_id=csm-set&limit=100` → `list[TradeRow]` (model from `csm.adapters.models`)
- [x] Mounted unconditionally in `api/main.py`; `public_mode_guard` denies `/api/v1/history/*` with 403 in public mode (matches existing convention for write paths). Protected by `APIKeyMiddleware` via the new `PROTECTED_PREFIXES` set in `api/security.py`.
- [x] Returns HTTP 503 with `{"detail": "<adapter> adapter unavailable (db_write_enabled is false or DSN missing)."}` when the corresponding adapter is `None`.
- [x] Pydantic v2 response schemas in `api/schemas/history.py` (re-exports adapter models).
- [x] Unit / integration tests cover schema validation, 503, auth, public-mode 403, and out-of-range query params.
- [x] Integration test (`infra_db`): write 10 days of equity; `GET ?days=30` returns 10 points in chronological order.

**Acceptance criteria:** `curl -H "X-API-Key: ..." 'http://localhost:8000/api/v1/history/equity-curve?days=30'` returns the last 30 days. ✅

#### 6.2 Performance & portfolio history

- [x] Endpoints:
  - `GET /performance?strategy_id=csm-set&days=30` → `list[DailyPerformanceRow]` (daily_return, cumulative_return, max_drawdown, sharpe_ratio, total_value, cash_balance, metadata)
  - `GET /portfolio-snapshots?days=30` → `list[PortfolioSnapshotRow]` (total_portfolio, weighted_return, active_strategies, allocation)
- [x] Integration test: write 3 days of performance + 2 portfolio snapshots; assert response length and field shape.

**Acceptance criteria:** External dashboards can fetch performance history without touching local files. ✅

#### 6.3 Backtest & signal history

- [x] Endpoints:
  - `GET /backtests?strategy_id=csm-set&limit=50` → `list[BacktestSummaryRow]`
  - `GET /signals?strategy_id=csm-set&date=YYYY-MM-DD` → `SignalSnapshotDoc` (404 when missing)
- [x] Integration test: write two backtests; the list contains both with the right run_ids; signals lookup by date returns the seeded document.

**Acceptance criteria:** Every backtest run + signal snapshot is reachable by `run_id` / `date` over REST. ✅

---

### Phase 7 — Testing & Hardening

**Status:** `[ ]` Not started
**Goal:** ≥ 90% coverage on `src/csm/adapters/`, full quality gate green, CI runs the integration suite against a real `quant-infra-db` stack on PR.

**Rationale:** Adapters are the IO boundary that touches another team's stack. Without an integration suite that exercises the live network and schemas, schema drift will silently break csm-set in production.

#### 7.1 Integration test suite

- [ ] Layout under `tests/integration/adapters/`:
  ```
  tests/integration/adapters/
  ├── conftest.py          # shared AdapterManager fixture + per-test teardown
  ├── test_postgres_io.py  # equity_curve / trade_history / backtest_log
  ├── test_mongo_io.py     # backtest_results / signal_snapshots / model_params
  ├── test_gateway_io.py   # daily_performance / portfolio_snapshot
  └── test_pipeline.py     # end-to-end refresh/backtest/rebalance → all DBs
  ```
- [ ] All tests carry `@pytest.mark.infra_db`; default `pytest` invocations exclude this marker.
- [ ] Teardown deletes everything where `strategy_id='test-csm-set'` (or equivalent test marker).
- [ ] CI workflow `.github/workflows/infra-integration.yml`:
  - Spins up `quant-infra-db` Compose stack as a service.
  - Sets `CSM_DB_*` env vars to the service hostnames.
  - Runs `uv run pytest tests/integration/adapters/ -v -m infra_db`.
  - Tears the stack down.

**Acceptance criteria:** `uv run pytest tests/integration/adapters/ -v -m infra_db` is green against the live stack and on the new CI workflow.

#### 7.2 Coverage & quality gate

- [ ] Add coverage gate to `pyproject.toml`:
  ```toml
  [tool.coverage.report]
  fail_under = 90
  include = ["src/csm/adapters/*"]
  ```
- [ ] `uv run ruff check .` — clean.
- [ ] `uv run ruff format --check .` — clean.
- [ ] `uv run mypy src/csm/adapters/` — strict, no errors (extends repo-wide mypy config).
- [ ] `uv run pytest tests/ -v` (unit + non-infra_db) — green.
- [ ] `uv run pytest tests/integration/adapters/ -m infra_db -v` — green when stack is up.

**Acceptance criteria:** All five quality gates pass on the feature branch.

#### 7.3 Documentation update

- [ ] Update `docs/architecture/overview.md` (or create the section if absent) with a write-back flow diagram:
  ```
  csm-set → AdapterManager ──▶ PostgresAdapter ──▶ quant-postgres (db_csm_set)
                          ──▶ GatewayAdapter  ──▶ quant-postgres (db_gateway)
                          ──▶ MongoAdapter    ──▶ quant-mongo    (csm_logs)
  ```
- [ ] Update `.env.example` — annotate the new variables with a one-line comment each.
- [ ] Update `README.md` — add "Persisting to quant-infra-db" section: prerequisites (stack running, network created), env vars to set, verification (`curl /health` shows `db.postgres=ok`).
- [ ] Add `CHANGELOG.md` entry under the current version.

**Acceptance criteria:** A new operator can enable write-back from `README.md` alone, with no source-code reading required.

---

## Data Flow Map

```
csm-set (live-test)
  ├── signals          →  MongoDB     csm_logs.signal_snapshots
  ├── equity curve     →  PostgreSQL  db_csm_set.equity_curve
  ├── trade history    →  PostgreSQL  db_csm_set.trade_history
  ├── backtest log     →  PostgreSQL  db_csm_set.backtest_log
  ├── backtest result  →  MongoDB     csm_logs.backtest_results
  ├── model params     →  MongoDB     csm_logs.model_params
  ├── daily perf       →  PostgreSQL  db_gateway.daily_performance
  └── portfolio snap   →  PostgreSQL  db_gateway.portfolio_snapshot
```

---

## Dependency Map

```
quant-infra-db Phase 1–5 (must be complete — external prerequisite)
        │
        ▼
Phase 1 — Connection & Config
        │
        ├──▶ Phase 2 — PostgreSQL Adapter (db_csm_set)
        ├──▶ Phase 3 — MongoDB Adapter (csm_logs)
        └──▶ Phase 4 — Gateway Adapter (db_gateway)
                    │
                    ▼
              Phase 5 — Pipeline Integration
                    │
                    ▼
              Phase 6 — API History Endpoints
                    │
                    ▼
              Phase 7 — Testing & Hardening
```

Phases 2, 3, and 4 may proceed in parallel after Phase 1.

---

## Error Handling Strategy

| Scenario | Behaviour |
|---|---|
| `db_write_enabled=False` | Adapters not constructed; pipeline hooks see `None` and skip silently |
| DSN missing while flag is on | Log warning at startup; that adapter alone is `None`; others initialise |
| `asyncpg.create_pool` fails at startup | Log error; adapter set to `None`; app continues; `/health` reports `error:<msg>` |
| Adapter write raises mid-pipeline | Hook logs WARNING; pipeline continues; data flushed locally as before |
| `ON CONFLICT` collision | Treated as upsert success; no error |
| `motor` write timeout | Caller catches `TimeoutError`; logs warning; continues |
| History endpoint with adapter `None` | Returns HTTP 503 with structured detail |
| `backtest_log` `run_id` collision | `ON CONFLICT (run_id) DO NOTHING` — silent no-op (run_id is the natural primary key) |
| Schema drift discovered in test | Test fails loudly with a `psycopg`/`asyncpg` error message; this is the intended canary |

No exception bubbles out of an adapter into a pipeline hook unmodified — every adapter call site uses a `try/except Exception` with a structured `logger.warning(...)`. This keeps csm-set's existing posture (best-effort persistence, never crash on IO).

---

## Testing Strategy

### Coverage targets

- `src/csm/adapters/` ≥ 90% line coverage (enforced in `pyproject.toml`).
- Adapter `write_*` methods ≥ 95% line coverage (these are the hot paths).
- Pipeline-hook code paths covered by both unit (mock adapter) and integration (`infra_db`) tests.

### Test layout

| Module | Test file |
|---|---|
| `src/csm/adapters/health.py` | `tests/unit/adapters/test_health.py` |
| `src/csm/adapters/postgres.py` | `tests/unit/adapters/test_postgres.py` + `tests/integration/adapters/test_postgres_io.py` |
| `src/csm/adapters/mongo.py` | `tests/unit/adapters/test_mongo.py` + `tests/integration/adapters/test_mongo_io.py` |
| `src/csm/adapters/gateway.py` | `tests/unit/adapters/test_gateway.py` + `tests/integration/adapters/test_gateway_io.py` |
| `src/csm/adapters/__init__.py` (`AdapterManager`) | `tests/unit/adapters/test_manager.py` |
| Pipeline hooks | `tests/integration/adapters/test_pipeline.py` |

### Markers

- `@pytest.mark.infra_db` — requires the `quant-infra-db` stack on `quant-network`. Skipped by default. Selected explicitly on the new CI workflow.
- Existing markers (`integration`, etc.) are unchanged.

### Fixtures (`tests/integration/adapters/conftest.py`)

- `adapter_manager` — yields a real `AdapterManager` initialised from env DSNs; closes on teardown.
- `clean_test_strategy` — autouse fixture deleting all rows / documents tagged `strategy_id='test-csm-set'` after each test.

---

## Exit Criteria

After Phase 7 completes:

- csm-set container resolves `quant-postgres` and `quant-mongo` over `quant-network` Docker DNS.
- `GET /health` reports `"db": {"postgres": "ok", "mongo": "ok"}` when the stack is up.
- A scheduled daily refresh produces new rows / documents in `equity_curve`, `signal_snapshots`, `daily_performance`, and `portfolio_snapshot` for the day.
- Every backtest run is captured in `backtest_log` (Postgres) and `backtest_results` (Mongo).
- Every rebalance event is captured in `trade_history`.
- Bringing the DB stack down does not crash csm-set; warnings are logged and pipelines continue.
- `GET /api/v1/history/equity-curve` (private mode) returns time series sourced from TimescaleDB.
- Coverage on `src/csm/adapters/` ≥ 90%.
- `uv run ruff check .`, `uv run mypy src/csm/adapters/`, `uv run pytest tests/ -v`, and `uv run pytest tests/integration/adapters/ -m infra_db -v` (with the stack up) all exit 0.
- `README.md` documents the enable-write-back flow end-to-end.

---

## Current Status

| Phase | Status | Notes |
|---|---|---|
| Phase 1 — Connection & Config | `[x]` | Complete 2026-05-06 |
| Phase 2 — PostgreSQL Adapter | `[x]` | Complete 2026-05-07. Includes Phase 6 read methods + Phase 5.1 AdapterManager skeleton (user-approved scope deviation). |
| Phase 3 — MongoDB Adapter | `[x]` | Complete 2026-05-07. Includes Phase 6 read methods (user-approved scope deviation, mirrors Phase 2 precedent). |
| Phase 4 — Gateway Adapter | `[x]` | Complete 2026-05-07. Includes Phase 6 read methods (user-approved scope deviation, mirrors Phase 2–3 precedents). |
| Phase 5 — Pipeline Integration | `[x]` | Complete 2026-05-07. All three hooks (post-refresh, post-backtest, post-rebalance) wired through AdapterManager. |
| Phase 6 — API History Endpoints | `[x]` | Complete 2026-05-07. Six GETs under `/api/v1/history/*` mounted unconditionally; `public_mode_guard` denies in public mode; APIKeyMiddleware gates via new `PROTECTED_PREFIXES`. Unit + `infra_db` integration tests pass. |
| Phase 7 — Testing & Hardening | `[ ]` | Coverage gate + CI workflow remain. |

---

## Commit & PR Templates

### Plan commit (this commit)

```
docs(plan): add master plan for csm-set-adapter feature

- 7-phase roadmap connecting csm-set to quant-infra-db
- PostgreSQL (db_csm_set, db_gateway) + MongoDB (csm_logs) write-back adapters
- Pipeline integration hooks for daily refresh, backtest, rebalance events
- Private-mode REST history endpoints + integration test suite (marker: infra_db)
- Phase 7 quality gate: ≥90% coverage on src/csm/adapters, mypy strict, ruff clean
```

### Per-phase commit messages

```
feat(adapters): wire asyncpg + motor settings; add /health DB check (Phase 1)

- Settings.db_csm_set_dsn / db_gateway_dsn / mongo_uri / db_write_enabled
- src/csm/adapters package skeleton + check_db_connectivity()
- docker-compose joins external quant-network
- /health response carries db.{postgres,mongo} status
```

```
feat(adapters): add PostgresAdapter for db_csm_set write-back (Phase 2)

- asyncpg pool (min=2,max=10) lifecycle + async context manager
- write_equity_curve / write_trade_history / write_backtest_log
- ON CONFLICT idempotency on every write
- Unit + infra_db integration tests
```

```
feat(adapters): add MongoAdapter for csm_logs write-back (Phase 3)

- motor.AsyncIOMotorClient lifecycle
- write_backtest_result / write_signal_snapshot / write_model_params
- Upsert keyed on natural identifiers
- Unit + infra_db integration tests
```

```
feat(adapters): add GatewayAdapter for db_gateway aggregates (Phase 4)

- write_daily_performance / write_portfolio_snapshot
- Multi-strategy-ready allocation JSONB column
- Unit + infra_db integration tests
```

```
feat(adapters): wire AdapterManager into pipeline hooks (Phase 5)

- AdapterManager.from_settings with graceful per-adapter degradation
- FastAPI lifespan owns the manager
- Post-refresh / post-backtest / post-rebalance hooks
- Best-effort writes — DB outage logs warning, never crashes
```

```
feat(api): add /api/v1/history/* private-mode endpoints (Phase 6)

- equity-curve / trades / performance / portfolio-snapshots / backtests / signals
- Pydantic v2 response schemas
- 503 when adapters unavailable
- API-key protected; private mode only
```

```
test(adapters): add infra_db integration suite + CI workflow (Phase 7)

- tests/integration/adapters/ with shared conftest + teardown
- @pytest.mark.infra_db marker; excluded by default
- .github/workflows/infra-integration.yml spins up quant-infra-db stack
- Coverage gate ≥90% on src/csm/adapters
- README + architecture overview updated
```

### PR template

```markdown
## Summary

`csm-set-adapter` — integration layer connecting csm-set to the quant-infra-db stack
(PostgreSQL + TimescaleDB + MongoDB on quant-network).

- Async write-back adapters: PostgresAdapter (db_csm_set), MongoAdapter (csm_logs),
  GatewayAdapter (db_gateway)
- AdapterManager coordinated from FastAPI lifespan with graceful degradation
- Pipeline hooks for daily refresh, backtest, rebalance events
- Private-mode REST history endpoints under /api/v1/history/*
- infra_db-marked integration suite + dedicated CI workflow
- Coverage ≥90% on src/csm/adapters; mypy strict; ruff clean

## Test plan

- [ ] `uv run pytest tests/unit/adapters/ -v`
- [ ] `uv run pytest tests/integration/adapters/ -v -m infra_db` (stack up)
- [ ] `uv run mypy src/csm/adapters/`
- [ ] `uv run ruff check .`
- [ ] `curl /health` shows `db.postgres=ok, db.mongo=ok`
- [ ] Trigger daily refresh; verify equity_curve / signal_snapshots / daily_performance grow
- [ ] Trigger backtest; verify backtest_log + backtest_results entries
- [ ] `curl /api/v1/history/equity-curve?days=30` (private mode) returns 30 points
```
