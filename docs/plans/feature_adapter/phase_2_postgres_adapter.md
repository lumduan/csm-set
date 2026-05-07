# Phase 2: PostgreSQL Adapter (`db_csm_set`)

**Feature:** csm-set-adapter — Integration layer connecting csm-set to quant-infra-db
**Branch:** `feature/csm-set-adapter`
**Created:** 2026-05-07
**Status:** Complete
**Completed:** 2026-05-07
**Depends On:** Phase 1 — Connection & Config (Complete 2026-05-06)

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Implementation Steps](#implementation-steps)
6. [File Changes](#file-changes)
7. [Acceptance Criteria](#acceptance-criteria)
8. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 2 turns the empty `src/csm/adapters/postgres.py` stub from Phase 1 into a working
`PostgresAdapter` that owns an `asyncpg` pool and exposes idempotent writes and typed reads
against the three `db_csm_set` tables (`equity_curve`, `trade_history`, `backtest_log`). It
also introduces the minimal `AdapterManager` skeleton and wires it into the FastAPI lifespan
so the adapter is actually live in the running app — both pulled forward from Phase 5 of the
master plan with explicit user approval.

After this phase:

- `PostgresAdapter` connects to `db_csm_set` via an `asyncpg` pool (`min_size=2, max_size=10`).
- Three idempotent write methods (`write_equity_curve`, `write_trade_history`,
  `write_backtest_log`) cover every Phase 5 hook target on the Postgres side.
- Three typed read methods return frozen Pydantic models for Phase 6 to wrap with routers.
- `AdapterManager` (Postgres-only this phase; Mongo/Gateway slots remain `None`) is
  constructed in the FastAPI lifespan and exposed via `app.state.adapters` and a DI getter.
- `/health` prefers a pool-based `SELECT 1` ping when the adapter is live, falling back to
  the existing Phase 1 short-lived check otherwise.

### Parent Plan Reference

- `docs/plans/feature_adapter/PLAN.md` — Master plan, Phase 2 section (lines 277–345),
  Phase 5.1 pulled forward, Phase 6 read-side pulled forward.

### Key Deliverables

1. **`src/csm/adapters/postgres.py`** — `PostgresAdapter` class (lifecycle + writes + reads).
2. **`src/csm/adapters/models.py`** — Frozen Pydantic models `EquityPoint`, `TradeRow`,
   `BacktestLogRow` for read returns.
3. **`src/csm/adapters/__init__.py`** — `AdapterManager` skeleton (Postgres-only).
4. **`api/main.py`** — lifespan wires manager into `app.state.adapters`; `/health` prefers
   pool ping.
5. **`api/deps.py`** — `get_adapter_manager()` DI provider.
6. **`tests/unit/adapters/test_postgres.py`** — Unit tests with mocked pool.
7. **`tests/unit/adapters/test_manager.py`** — Unit tests for `AdapterManager`.
8. **`tests/integration/adapters/test_postgres_io.py`** — `infra_db` integration tests.
9. **`tests/integration/adapters/conftest.py`** — Shared adapter fixture + teardown.

---

## AI Prompt

The following prompt was used to generate this phase:

```
You are tasked with implementing Phase 2 — PostgreSQL Adapter (db_csm_set) for the csm-set
project. Follow these steps precisely:

1. Preparation
   - Carefully read .claude/knowledge/project-skill.md and .claude/playbooks/feature-development.md
     to internalize all engineering standards and workflow expectations.
   - Review docs/plans/feature_adapter/PLAN.md, focusing on the Phase 2 section, and ensure you
     understand all deliverables, acceptance criteria, and architectural context.
   - Review docs/plans/feature_adapter/phase_1_connection_and_config.md for the current state
     and prior implementation details.

2. Planning
   - Draft a detailed implementation plan for Phase 2 in markdown, using the format from
     docs/plans/examples/phase1-sample.md.
   - Your plan must include: scope, deliverables, acceptance criteria, risks, and the full AI
     agent prompt (this prompt).
   - Save the plan as docs/plans/feature_adapter/phase_2_postgres_adapter.md.

3. Implementation
   - Only begin coding after the plan is complete and saved.
   - Implement all deliverables for Phase 2:
     - Implement the PostgreSQL adapter for db_csm_set in src/csm/adapters/postgres.py, using
       asyncpg connection pooling, type-safe queries, and Pydantic models for all data
       structures.
     - Provide methods for basic CRUD operations and any required business logic.
     - Add comprehensive unit and integration tests.
     - Ensure robust error handling, logging, and retry logic.
     - Update and extend documentation as needed.
   - Ensure all code follows project standards: type safety, async/await, Pydantic validation,
     error handling, and import organization.

4. Documentation and Progress Tracking
   - Update docs/plans/feature_adapter/PLAN.md and docs/plans/feature_adapter/phase_2_postgres_adapter.md
     with progress notes, completion status, and any issues encountered.
   - Mark acceptance criteria as completed or note any deviations.

5. Commit and Finalization
   - Commit all changes in a single commit with a clear, standards-compliant message
     summarizing the work.
   - Ensure all tests pass and the implementation meets the acceptance criteria.

Files to reference and/or modify:
- .claude/knowledge/project-skill.md
- .claude/playbooks/feature-development.md
- docs/plans/feature_adapter/PLAN.md
- docs/plans/feature_adapter/phase_1_connection_and_config.md
- docs/plans/examples/phase1-sample.md
- .env (for DB secrets)
- src/csm/adapters/postgres.py
- src/csm/adapters/
- Test and documentation files as needed

Expected deliverables:
- A new plan markdown file at docs/plans/feature_adapter/phase_2_postgres_adapter.md with the
  full implementation plan and embedded prompt.
- All Phase 2 deliverables implemented and tested.
- Updated progress/completion notes in both docs/plans/feature_adapter/PLAN.md and the new
  phase plan file.
- A single commit with all changes and a standards-compliant message.

Begin by drafting the plan markdown file. Do not start implementation until the plan is
complete and saved.
```

---

## Scope

### In Scope (Phase 2)

| Component | Description | Status |
|---|---|---|
| `PostgresAdapter` lifecycle | `__init__(dsn)` / `connect()` / `close()` / `__aenter__` / `__aexit__` / `ping()` | `[x]` |
| asyncpg pool | `create_pool(min_size=2, max_size=10, command_timeout=30)` | `[x]` |
| `_SQL` constants | Frozen dataclass holding the four canonical statements | `[x]` |
| `write_equity_curve` | `executemany` upsert on `(time, strategy_id)`; returns row count | `[x]` |
| `write_trade_history` | `executemany` upsert on `(strategy_id, time, symbol, side)` | `[x]` |
| `write_backtest_log` | Single insert; `ON CONFLICT (run_id) DO NOTHING`; JSONB for config/summary | `[x]` |
| `read_equity_curve` | Returns `list[EquityPoint]` ordered by time ascending | `[x]` |
| `read_trade_history` | Returns `list[TradeRow]` ordered by time descending | `[x]` |
| `read_backtest_log` | Returns `list[BacktestLogRow]`; optional `strategy_id` filter | `[x]` |
| Adapter Pydantic models | `EquityPoint`, `TradeRow`, `BacktestLogRow` (frozen v2) | `[x]` |
| `AdapterManager` skeleton | Postgres-only this phase; Mongo/Gateway = `None`; `from_settings` + `close` + `ping` | `[x]` |
| FastAPI lifespan wiring | Manager constructed/closed in `lifespan`; stored on `app.state.adapters` | `[x]` |
| DI provider | `get_adapter_manager(request)` in `api/deps.py` | `[x]` |
| `/health` pool ping | Uses `manager.ping()` when adapter live; short-lived fallback otherwise | `[x]` |
| Unit tests — `test_postgres.py` | Mocked pool; lifecycle + writes + reads | `[x]` |
| Unit tests — `test_manager.py` | Disabled flag, missing DSN, connect failure paths | `[x]` |
| Unit tests — `test_api_lifespan.py` | Assert `app.state.adapters` set | `[x]` |
| Integration tests | `infra_db`-marked; idempotency + read round-trip; teardown | `[x]` |
| PLAN.md updates | Progress flips + scope-deviation annotations for Phase 5.1 / Phase 6 | `[x]` |

### Out of Scope (Phase 2)

- MongoAdapter / GatewayAdapter implementations (Phases 3–4).
- Pipeline hooks (post-refresh / post-backtest / post-rebalance) — Phase 5.2–5.4.
- API history endpoints (`/api/v1/history/*`) — Phase 6.
- DDL or migrations — owned by `quant-infra-db`.
- Coverage gate enforcement on `src/csm/adapters/` — Phase 7.
- CI workflow for `infra_db` tests — Phase 7.

---

## Design Decisions

### 1. Pool sizing fixed at `min_size=2, max_size=10`

Per master plan §2.1. Two persistent connections cover the daily-refresh / rebalance load
without leaving idle sockets, while ten upper-bounds peak concurrency from API history
endpoints and parallel backtest jobs. `command_timeout=30` guards against runaway queries.

### 2. SQL constants in a frozen `_SQL` dataclass

A module-level `@dataclass(frozen=True)` instance named `_SQL` holds every statement.
Method bodies reference `_SQL.UPSERT_EQUITY` etc. — never inline string concatenation.
This satisfies PLAN.md §2.1 ("Centralised SQL constants in a private `_SQL` namespace
(no inline string concatenation)") and makes statement audits trivial.

### 3. DataFrame inputs allowed for batch writes

`write_equity_curve` accepts `pd.Series` and `write_trade_history` accepts `pd.DataFrame`,
per the project-wide DataFrame exception called out in PLAN.md line 108: DataFrames are the
natural shape for OHLCV-style bulk data and forcing them through Pydantic at this boundary
adds cost without value. All other adapter inputs and **all read return values** are typed
(dict / Pydantic model).

### 4. Reads return frozen Pydantic models

`read_equity_curve` / `read_trade_history` / `read_backtest_log` return
`list[EquityPoint]` / `list[TradeRow]` / `list[BacktestLogRow]`. Models live in
`src/csm/adapters/models.py` so Phase 6 can either import them directly or wrap them with
narrower API response types. Frozen with `ConfigDict(frozen=True)` to match the project's
existing convention (e.g., `HealthStatus`, `TradingViewCookies`).

### 5. No internal try/except in adapter writes

Adapter `write_*` methods do not swallow exceptions. The caller (Phase 5 hooks) wraps each
call in `try/except Exception: logger.warning(...)` per the master plan's error-handling
table. This keeps adapter responsibilities sharp: own the SQL + the pool, surface errors
verbatim, leave best-effort policy to the call site.

### 6. No hand-rolled retry loop

`asyncpg`'s pool already reconnects transparently on dropped connections and surfaces real
errors only when reconnection itself fails. Adding a retry loop in the adapter would
duplicate that logic and risk turning a real DB outage into a long-tail latency spike.
Phase 5 hooks log + skip on failure; that is the retry model.

### 7. `AdapterManager.from_settings` never raises

Even when `db_write_enabled=True` and a DSN is set, a failed `connect()` results in
`postgres=None` plus a structured `logger.warning`. Application boot continues. This
matches PLAN.md error-handling row "asyncpg.create_pool fails at startup → Log error;
adapter set to None; app continues; /health reports error:<msg>".

### 8. `/health` prefers pool ping when manager.postgres is live

When `app.state.adapters.postgres` is not `None`, `/health` calls `manager.ping()`, which
runs `SELECT 1` through the live pool. This catches dead pools (which short-lived
`asyncpg.connect()` would not see). When the manager has no Postgres adapter, `/health`
falls back to the existing Phase 1 `check_db_connectivity(settings)` so behaviour is
unchanged when `db_write_enabled=False`. Mongo continues to use the short-lived check.

### 9. Two scope deviations from master plan (user-approved)

| Deviation | Source | Rationale |
|---|---|---|
| Read methods added in Phase 2 | Originally Phase 6 | Keeps the SQL surface in one place; Phase 6 only adds routers + response schemas. Approved by user 2026-05-07. |
| `AdapterManager` skeleton + lifespan wiring in Phase 2 | Originally Phase 5.1 | Makes the adapter actually live in the running app; Phase 5.2–5.4 hooks still pending. Approved by user 2026-05-07. |

---

## Implementation Steps

### Step 1: Adapter-level Pydantic models

Create `src/csm/adapters/models.py` with frozen v2 models — `EquityPoint(time, strategy_id, equity)`,
`TradeRow(time, strategy_id, symbol, side, quantity, price, commission)`,
`BacktestLogRow(run_id, strategy_id, created_at, config, summary)`. Public re-exports.

### Step 2: `PostgresAdapter` class

Replace the stub at `src/csm/adapters/postgres.py` with the full class. Module-level `_SQL`
frozen dataclass. Lifecycle methods (`connect`/`close`/`__aenter__`/`__aexit__`/`ping`).
Three writes (`write_equity_curve`/`write_trade_history`/`write_backtest_log`).
Three reads (`read_equity_curve`/`read_trade_history`/`read_backtest_log`).
Google-style docstrings on every public method. Strict typing.

### Step 3: `AdapterManager`

Implement in `src/csm/adapters/__init__.py`. Class fields: `postgres: PostgresAdapter | None`
and reserved `mongo: None` / `gateway: None` slots. Classmethod
`from_settings(settings) -> AdapterManager` that constructs and connects the Postgres adapter
when `db_write_enabled=True` and `db_csm_set_dsn` is set, otherwise returns the manager with
`postgres=None`. Connect failures are logged and turned into `postgres=None`. `close()`
closes whatever was opened. `ping()` returns `{"postgres": "ok"|"error:..."}` or `None`.

### Step 4: FastAPI lifespan + DI

In `api/main.py` `lifespan`: build the manager via `AdapterManager.from_settings(settings)`,
store on `app.state.adapters`, await close on shutdown. Update `/health` to prefer
`manager.ping()` when `manager.postgres is not None`, falling back to
`check_db_connectivity(settings)`. Mongo continues to use the short-lived path.
In `api/deps.py`: add `get_adapter_manager(request) -> AdapterManager` paralleling
`get_store()`.

### Step 5: Unit tests

`tests/unit/adapters/test_postgres.py`:

- Lifecycle: `connect` calls `asyncpg.create_pool(min_size=2, max_size=10, ...)`; `close` closes the pool; both idempotent.
- Context manager calls connect + close.
- `ping` returns True when `fetchval` returns 1; False otherwise.
- `write_equity_curve` builds 252 tuples and calls `executemany` once with the upsert SQL.
- `write_trade_history` builds N tuples from a DataFrame.
- `write_backtest_log` calls `execute` with JSON-serialised config/summary and `ON CONFLICT (run_id) DO NOTHING`.
- Each read parses fetched rows into the expected Pydantic model list.

`tests/unit/adapters/test_manager.py`:

- `db_write_enabled=False` → all adapters `None`; `ping()` returns `None`.
- DSN missing → `postgres=None`, warning logged.
- `connect()` raises → `postgres=None`, warning logged, no re-raise.
- `from_settings` happy path (mocked `PostgresAdapter.connect`) wires `postgres` correctly.
- `ping()` reflects pool status.

`tests/unit/test_api_lifespan.py`: add a test asserting `app.state.adapters` is an
`AdapterManager` after lifespan startup.

### Step 6: Integration tests

`tests/integration/adapters/conftest.py`: yields a connected `PostgresAdapter` from the
real `CSM_DB_CSM_SET_DSN`; closes on teardown; an autouse fixture wipes
`strategy_id='test-csm-set'` rows from all three tables. Skip if DSN not set.

`tests/integration/adapters/test_postgres_io.py` (`@pytest.mark.infra_db`):

- `test_write_equity_curve_idempotent`: write 252 rows; rerun; count remains 252.
- `test_write_trade_history_idempotent`: same shape on `(strategy_id, time, symbol, side)`.
- `test_write_backtest_log_run_id_collision_no_op`: second write with same `run_id` is a no-op.
- `test_read_equity_curve_returns_models`: ascending order; `len == days`.
- `test_read_trade_history_descending_limit`.
- `test_read_backtest_log_filter_by_strategy`.

### Step 7: PLAN.md updates

Flip Phase 2 checkboxes. Annotate Phase 5.1 and Phase 6 with the scope-deviation notes.
Update Current Status table.

### Step 8: Quality gates

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src/ api/ && uv run pytest tests/ -v
```

All four must pass before commit. Integration tests run only when stack is up.

### Step 9: Commit

Single commit with the standards-compliant message in the master plan §"Per-phase commit
messages".

---

## File Changes

| File | Action | Description |
|---|---|---|
| `src/csm/adapters/models.py` | CREATE | `EquityPoint`, `TradeRow`, `BacktestLogRow` |
| `src/csm/adapters/postgres.py` | MODIFY | Replace stub with full `PostgresAdapter` |
| `src/csm/adapters/__init__.py` | MODIFY | Add `AdapterManager` skeleton + re-exports |
| `api/main.py` | MODIFY | Manager in lifespan; pool-aware `/health` |
| `api/deps.py` | MODIFY | `get_adapter_manager()` DI provider |
| `tests/unit/adapters/test_postgres.py` | CREATE | Mocked-pool unit tests |
| `tests/unit/adapters/test_manager.py` | CREATE | `AdapterManager` unit tests |
| `tests/unit/test_api_lifespan.py` | MODIFY | Assert `app.state.adapters` set |
| `tests/integration/adapters/conftest.py` | CREATE | Adapter fixture + teardown |
| `tests/integration/adapters/test_postgres_io.py` | CREATE | `infra_db` integration tests |
| `docs/plans/feature_adapter/PLAN.md` | MODIFY | Progress flips + deviation notes |
| `docs/plans/feature_adapter/phase_2_postgres_adapter.md` | CREATE | This document |

---

## Acceptance Criteria

- [x] `uv run mypy src/csm/adapters/ api/` clean.
- [x] `uv run ruff check .` and `uv run ruff format --check .` clean.
- [x] `uv run pytest tests/unit/adapters/ -v` green.
- [x] `uv run pytest tests/ -v` green (full suite, no infra_db tests).
- [x] `PostgresAdapter` instantiable without a live DB; `connect()` failure does not crash app boot.
- [x] `app.state.adapters` is an `AdapterManager` after lifespan startup.
- [x] `/health` returns `"db": null` when `db_write_enabled=False` (Phase 1 contract preserved).
- [x] `/health` returns `"db": {"postgres": "ok", ...}` via pool ping when adapter is live.
- [x] With `quant-infra-db` stack up: `uv run pytest tests/integration/adapters/ -m infra_db -v` green.
- [x] Re-running `write_equity_curve` / `write_trade_history` / `write_backtest_log` produces no duplicate rows (idempotent).
- [x] Reads round-trip writes correctly and return frozen Pydantic models.
- [x] PLAN.md updated with progress flips and the two scope-deviation annotations.

---

## Completion Notes

### Summary

Phase 2 complete. All deliverables implemented in a single session:

- **2.1 Lifecycle:** `PostgresAdapter` owns one `asyncpg.Pool` (`min_size=2, max_size=10, command_timeout=30`). `connect`/`close` are idempotent; `__aenter__` / `__aexit__` make the adapter usable as an async context manager; `ping()` runs `SELECT 1` through the pool. SQL statements live on a frozen `_SQLStatements` dataclass; no inline string concatenation. A pool `init` callback registers a JSONB type codec so dicts round-trip cleanly.
- **2.2–2.4 Writes:** `write_equity_curve`, `write_trade_history`, and `write_backtest_log` use `executemany` / `execute` with the exact `ON CONFLICT` clauses called out in the master plan. `write_trade_history` validates required columns up front. `write_backtest_log` JSON-serialises both `config` and `summary` and inserts them with explicit `$3::jsonb` / `$4::jsonb` casts so the codec choice is robust to operator-side casting differences.
- **2.5 Reads (pulled forward from Phase 6):** `read_equity_curve`, `read_trade_history`, `read_backtest_log` return frozen Pydantic models defined in `src/csm/adapters/models.py`. The `read_backtest_log` implementation tolerates the rare case where JSONB returns as a non-dict (e.g. before the codec is registered) by coercing to `{}`.
- **2.6 AdapterManager + lifespan (pulled forward from Phase 5.1):** Manager constructed via `AdapterManager.from_settings(settings)`; missing DSN and connect-failure paths both downgrade to `postgres=None` with structured `logger.warning` and never raise. FastAPI lifespan wires the manager onto `app.state.adapters` and awaits `manager.close()` on shutdown. `api/deps.py` exposes `get_adapter_manager` for handler DI. `/health` merges `manager.ping()` results over the existing short-lived `check_db_connectivity()` so `db_write_enabled=False` continues to return `db: null` and the pool ping is preferred when the adapter is live.
- **Tests:** Unit suite in `tests/unit/adapters/test_postgres.py` (lifecycle, ping guard, every write/read with mocked pool) and `tests/unit/adapters/test_manager.py` (every degradation path). `tests/unit/test_api_lifespan.py` extended to assert `app.state.adapters` is an `AdapterManager`. Integration suite under `tests/integration/adapters/test_postgres_io.py` exercises idempotency on all three writes and round-trips reads, with a shared `conftest.py` that auto-wipes `strategy_id='test-csm-set'` before and after every test.

### Issues Encountered

1. **Two scope deviations agreed up front (recorded in Design Decisions §9).** Read methods (Phase 6) and the `AdapterManager` skeleton (Phase 5.1) were pulled into Phase 2 with explicit user approval rather than handled as drift. PLAN.md §5.1 / §6 / Current Status table were updated to reflect this.
2. **JSONB round-trip default.** asyncpg returns JSONB columns as raw strings unless a codec is set. Solved once at pool-init time (`set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads)`) so adapter callers always see plain dicts. The `_record_to_backtest_log` helper still defends against a missing codec (e.g. when integration tests run against a server that returns the column under a different oid) by coercing non-dict values to `{}`.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.7)
**Status:** Complete
**Completed:** 2026-05-07
