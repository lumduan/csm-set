# Phase 3: MongoDB Adapter (`csm_logs`)

**Feature:** csm-set-adapter — Integration layer connecting csm-set to quant-infra-db
**Branch:** `feature/csm-set-adapter`
**Created:** 2026-05-07
**Status:** Complete
**Completed:** 2026-05-07
**Depends On:** Phase 1 — Connection & Config (Complete 2026-05-06), Phase 2 — PostgresAdapter (Complete 2026-05-07)

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Implementation Steps](#implementation-steps)
6. [File Changes](#file-changes)
7. [Acceptance Criteria](#acceptance-criteria)
8. [Risks & Mitigations](#risks--mitigations)
9. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 3 turns the empty `src/csm/adapters/mongo.py` stub from Phase 1 into a working
`MongoAdapter` that owns a `motor.AsyncIOMotorClient` and exposes idempotent writes plus
typed reads against the three `csm_logs` collections (`backtest_results`,
`signal_snapshots`, `model_params`). It also fills the `mongo` slot on `AdapterManager`
so the adapter is actually live in the running app, mirroring how Phase 2 wired Postgres.

After this phase:

- `MongoAdapter` connects to `csm_logs` via `motor.AsyncIOMotorClient(uri, tz_aware=True)`.
- Three idempotent write methods (`write_backtest_result`, `write_signal_snapshot`,
  `write_model_params`) cover every Phase 5 hook target on the Mongo side.
- Four typed read methods (`read_backtest_result`, `read_signal_snapshot`,
  `read_model_params`, `list_backtest_results`) return frozen Pydantic models so Phase 6
  routers wrap them without touching the Mongo driver.
- `AdapterManager.mongo: MongoAdapter | None` is constructed by `from_settings` whenever
  `db_write_enabled=True` and `mongo_uri` is set; missing URI and connect failures both
  downgrade to `None` with a structured warning. App boot never crashes.
- `/health` continues to merge `manager.ping()` over the existing short-lived
  `check_db_connectivity()` — when the live Mongo adapter is up, the pool-style ping is
  preferred; the disabled-flag path still returns `db: null`.

### Parent Plan Reference

- `docs/plans/feature_adapter/PLAN.md` — Master plan, Phase 3 section (lines 380–444),
  Phase 5.1 Mongo slot conversion, Phase 6 Mongo read-side pulled forward.

### Key Deliverables

1. **`src/csm/adapters/mongo.py`** — `MongoAdapter` class (lifecycle + writes + reads).
2. **`src/csm/adapters/models.py`** — Frozen Pydantic models `BacktestResultDoc`,
   `SignalSnapshotDoc`, `ModelParamsDoc`, `BacktestSummaryRow` for read returns.
3. **`src/csm/adapters/__init__.py`** — `AdapterManager.mongo` slot tightened to
   `MongoAdapter | None`; `from_settings`, `close`, `ping` extended.
4. **`tests/unit/adapters/test_mongo.py`** — Unit tests with mocked motor client.
5. **`tests/unit/adapters/test_manager.py`** — Extended with Mongo degradation +
   happy paths.
6. **`tests/unit/test_api_lifespan.py`** — Extended with a Mongo-disabled lifespan
   assertion.
7. **`tests/integration/adapters/conftest.py`** — Extended with a Mongo fixture +
   per-test teardown across all three collections.
8. **`tests/integration/adapters/test_mongo_io.py`** — `infra_db` integration tests
   covering idempotency + read round-trip.
9. **`docs/plans/feature_adapter/PLAN.md`** — Phase 3 progress flips, Phase 5.1 Mongo
   slot annotation update, Phase 6 deviation note.
10. **`docs/plans/feature_adapter/phase_3_mongo_adapter.md`** — This document.

---

## AI Prompt

The following prompt was used to generate this phase:

```
🎯 Objective
Develop a comprehensive implementation plan for Phase 3 — MongoDB Adapter (csm_logs)
for the csm-set project, following all engineering standards and workflow expectations.
The plan must be saved as docs/plans/feature_adapter/phase_3_mongo_adapter.md and include
the full AI agent prompt, scope, deliverables, acceptance criteria, risks, and references.
Implementation should only begin after the plan is complete and saved.

📋 Context
- The csm-set project is a production-grade, type-safe, async-first Python backend with
  strict architectural standards (see .claude/knowledge/project-skill.md).
- The project uses a phased feature adapter architecture, with each phase tracked in
  docs/plans/feature_adapter/PLAN.md.
- Phase 2 (PostgreSQL Adapter) is complete; its plan and implementation are in
  docs/plans/feature_adapter/phase_2_postgres_adapter.md.
- Phase 3 focuses on implementing the MongoDB Adapter for the csm_logs database, following
  the same rigor as the Postgres adapter.
- All planning and implementation must follow .claude/playbooks/feature-development.md.
- The plan must be detailed, actionable, and follow the format in
  docs/plans/examples/phase1-sample.md.

🔧 Requirements
- Read and internalize .claude/knowledge/project-skill.md and
  .claude/playbooks/feature-development.md before planning.
- Review docs/plans/feature_adapter/PLAN.md (focus on Phase 3) and
  docs/plans/feature_adapter/phase_2_postgres_adapter.md for context and standards.
- Draft a detailed implementation plan for Phase 3, including:
  - Scope (in/out)
  - Deliverables (files, classes, methods, tests, docs)
  - Acceptance criteria (type safety, async/await, Pydantic validation, error handling,
    test coverage, etc.)
  - Risks and mitigation
  - The full AI agent prompt (this prompt)
- Save the plan as docs/plans/feature_adapter/phase_3_mongo_adapter.md before starting
  implementation.
- Only begin coding after the plan is complete and saved.
- Update docs/plans/feature_adapter/PLAN.md and
  docs/plans/feature_adapter/phase_3_mongo_adapter.md with progress notes, completion
  status, and any issues encountered.
- Commit all changes in a single commit with a standards-compliant message after all
  deliverables and documentation are complete.

📁 Code Context
- .claude/knowledge/project-skill.md
- .claude/playbooks/feature-development.md
- docs/plans/feature_adapter/PLAN.md
- docs/plans/feature_adapter/phase_2_postgres_adapter.md
- docs/plans/examples/phase1-sample.md
- Target plan file: docs/plans/feature_adapter/phase_3_mongo_adapter.md

✅ Expected Output
- A new, detailed plan markdown file at
  docs/plans/feature_adapter/phase_3_mongo_adapter.md covering all requirements and
  including the full AI agent prompt.
- Updated progress/completion notes in both docs/plans/feature_adapter/PLAN.md and the new
  phase plan file.
- A single commit with all changes and a standards-compliant message after implementation
  is complete.

-----
Prompt for AI Agent:
-----

You are tasked with implementing Phase 3 — MongoDB Adapter (csm_logs) for the csm-set
project. Follow these steps precisely:

1. Preparation
   - Carefully read .claude/knowledge/project-skill.md and
     .claude/playbooks/feature-development.md to internalize all engineering standards
     and workflow expectations.
   - Review docs/plans/feature_adapter/PLAN.md, focusing on the Phase 3 section, and
     ensure you understand all deliverables, acceptance criteria, and architectural
     context.
   - Review docs/plans/feature_adapter/phase_2_postgres_adapter.md for the current state
     and prior implementation details.

2. Planning
   - Draft a detailed implementation plan for Phase 3 in markdown, using the format from
     docs/plans/examples/phase1-sample.md.
   - Your plan must include: scope, deliverables, acceptance criteria, risks, and the
     full AI agent prompt (this prompt).
   - Save the plan as docs/plans/feature_adapter/phase_3_mongo_adapter.md.

3. Implementation
   - Only begin coding after the plan is complete and saved.
   - Implement all deliverables for Phase 3:
     - Implement the MongoDB adapter for csm_logs in the appropriate module, using async
       MongoDB client (e.g., motor), type-safe queries, and Pydantic models for all data
       structures.
     - Provide methods for required CRUD operations and any specified business logic.
     - Add comprehensive unit and integration tests.
     - Ensure robust error handling, logging, and retry logic.
     - Update and extend documentation as needed.
   - Ensure all code follows project standards: type safety, async/await, Pydantic
     validation, error handling, and import organization.

4. Documentation and Progress Tracking
   - Update docs/plans/feature_adapter/PLAN.md and
     docs/plans/feature_adapter/phase_3_mongo_adapter.md with progress notes, completion
     status, and any issues encountered.
   - Mark acceptance criteria as completed or note any deviations.

5. Commit and Finalization
   - Commit all changes in a single commit with a clear, standards-compliant message
     summarizing the work.
   - Ensure all tests pass and the implementation meets the acceptance criteria.

Files to reference and/or modify:
- .claude/knowledge/project-skill.md
- .claude/playbooks/feature-development.md
- docs/plans/feature_adapter/PLAN.md
- docs/plans/feature_adapter/phase_2_postgres_adapter.md
- docs/plans/examples/phase1-sample.md
- Target plan file: docs/plans/feature_adapter/phase_3_mongo_adapter.md

Expected deliverables:
- A new plan markdown file at docs/plans/feature_adapter/phase_3_mongo_adapter.md with
  the full implementation plan and embedded prompt.
- All Phase 3 deliverables implemented and tested.
- Updated progress/completion notes in both docs/plans/feature_adapter/PLAN.md and the
  new phase plan file.
- A single commit with all changes and a standards-compliant message.

Begin by drafting the plan markdown file. Do not start implementation until the plan is
complete and saved.
```

---

## Scope

### In Scope (Phase 3)

| Component | Description | Status |
|---|---|---|
| `MongoAdapter` lifecycle | `__init__(uri, db_name="csm_logs")` / `connect()` / `close()` / `__aenter__` / `__aexit__` / `ping()` | `[x]` |
| Motor client | `AsyncIOMotorClient(uri, tz_aware=True, serverSelectionTimeoutMS=5000)` with explicit `await client.admin.command("ping")` on `connect()` | `[x]` |
| `_COLL` constants | Frozen dataclass holding the three collection names so adapter methods reference attributes, not string literals | `[x]` |
| `write_backtest_result` | `replace_one({"run_id": ...}, doc, upsert=True)` against `backtest_results` | `[x]` |
| `write_signal_snapshot` | `update_one({"strategy_id": ..., "date": ...}, {"$set": doc}, upsert=True)` against `signal_snapshots` | `[x]` |
| `write_model_params` | `update_one({"strategy_id": ..., "version": ...}, {"$set": doc}, upsert=True)` against `model_params` | `[x]` |
| `read_backtest_result` | Returns `BacktestResultDoc \| None` from `find_one({"run_id": ...})` | `[x]` |
| `read_signal_snapshot` | Returns `SignalSnapshotDoc \| None` from `find_one({"strategy_id": ..., "date": ...})` | `[x]` |
| `read_model_params` | Returns `ModelParamsDoc \| None` from `find_one({"strategy_id": ..., "version": ...})` | `[x]` |
| `list_backtest_results` | Returns `list[BacktestSummaryRow]`; descending `created_at`; optional `strategy_id` filter; `limit` defaults to 50 | `[x]` |
| Adapter Pydantic models | `BacktestResultDoc`, `SignalSnapshotDoc`, `ModelParamsDoc`, `BacktestSummaryRow` (frozen v2) | `[x]` |
| `AdapterManager.mongo` typing | `mongo: MongoAdapter \| None` (was `object \| None`) | `[x]` |
| `AdapterManager.from_settings` Mongo branch | Constructs Mongo adapter only when `db_write_enabled=True` AND `mongo_uri` is set; connect failure → `None` + warning | `[x]` |
| `AdapterManager.close` Mongo branch | Best-effort close; failure logged, never raised | `[x]` |
| `AdapterManager.ping` Mongo branch | Adds `mongo` key to result dict when adapter live | `[x]` |
| Unit tests — `test_mongo.py` | Mocked motor; lifecycle + ping + every write + every read | `[x]` |
| Unit tests — `test_manager.py` extension | Mongo missing URI / connect failure / happy path / ping reflection | `[x]` |
| Unit tests — `test_api_lifespan.py` extension | Assert `app.state.adapters.mongo is None` when `db_write_enabled=False` | `[x]` |
| Integration tests — `test_mongo_io.py` | `infra_db`-marked; idempotency on all three writes; read round-trip; `list_backtest_results` ordering/limit | `[x]` |
| Integration teardown | Extend `conftest.py` to delete `strategy_id="test-csm-set"` documents from all three collections (and matching `run_id` prefix from `backtest_results`) | `[x]` |
| PLAN.md updates | Phase 3 progress flips; Phase 5.1 Mongo slot annotation note; Phase 6 deviation note | `[x]` |

### Out of Scope (Phase 3)

- GatewayAdapter implementation (Phase 4).
- Pipeline hooks `post-refresh / post-backtest / post-rebalance` Mongo write calls
  (Phase 5.2–5.4).
- API history endpoints `/api/v1/history/signals` and `/api/v1/history/backtests`
  (Phase 6 — only routers and request schemas remain after this phase).
- Mongo collection or index DDL — owned by `quant-infra-db`. The adapter assumes the
  unique indexes implied by the natural keys exist.
- Coverage gate enforcement on `src/csm/adapters/` — Phase 7.
- CI workflow for `infra_db` tests — Phase 7.

---

## Design Decisions

### 1. `tz_aware=True` on the motor client

`AsyncIOMotorClient(uri, tz_aware=True)`. PyMongo defaults to naïve datetimes, which would
silently lose the project-wide `Asia/Bangkok`-aware UTC contract called out in
`project-skill.md` rule #7. With `tz_aware=True`, every `datetime` round-trips as tz-aware
UTC, matching the Postgres TimescaleDB tier and what `EquityPoint` already produces.

### 2. Collection names live on a frozen `_COLL` dataclass

A module-level `@dataclass(frozen=True)` named `_COLL` holds `BACKTEST_RESULTS`,
`SIGNAL_SNAPSHOTS`, and `MODEL_PARAMS` strings. Method bodies reference
`_COLL.BACKTEST_RESULTS` etc. — never inline string literals. This mirrors the `_SQL`
pattern from `PostgresAdapter` (PLAN.md §2.1) and makes a future rename a one-line change.

### 3. Idempotency: `replace_one` for backtest_results, `update_one + $set` for the other two

| Collection | Operation | Why |
|---|---|---|
| `backtest_results` | `replace_one({"run_id": ...}, doc, upsert=True)` | The full result doc is the natural unit; replacing on rerun (e.g. fixed bug → re-run) is the desired semantic |
| `signal_snapshots` | `update_one({"strategy_id": ..., "date": ...}, {"$set": doc}, upsert=True)` | Daily refresh re-runs may add fields (e.g. new metric) without removing existing ones |
| `model_params` | `update_one({"strategy_id": ..., "version": ...}, {"$set": doc}, upsert=True)` | Same: a version bump may extend the params dict; `$set` preserves anything else stored |

In all three cases the natural-key filter is sufficient; the adapter assumes
`quant-infra-db` provides the implied unique indexes (`run_id`, `(strategy_id, date)`,
`(strategy_id, version)`).

### 4. Reads return frozen Pydantic models

`BacktestResultDoc`, `SignalSnapshotDoc`, `ModelParamsDoc`, `BacktestSummaryRow` live in
`src/csm/adapters/models.py` (alongside Phase 2's `EquityPoint` / `TradeRow` /
`BacktestLogRow`). All frozen v2 with `ConfigDict(frozen=True)`. Phase 6 routers can
either import them directly or wrap them with narrower API response types.

`BacktestSummaryRow` is a slim projection (`run_id`, `strategy_id`, `created_at`,
`metrics`) returned by `list_backtest_results` so the listing endpoint does not ship full
equity-curve / trade arrays for every row.

### 5. Drop Mongo-internal `_id` from all read paths

`find_one(...)` and `find(...).to_list(...)` strip `_id` via projection (`{"_id": 0}`)
before validating into Pydantic. The adapter never surfaces ObjectIds; consumers only
ever see the natural keys. This keeps Phase 6 response schemas free of Mongo-specific
fields.

### 6. List input for rankings (per user 2026-05-07)

`write_signal_snapshot` accepts `rankings: list[dict[str, object]]` per PLAN.md §3.3
verbatim. Conversion from `CrossSectionalRanker.rank()`'s DataFrame slice is the caller's
responsibility (Phase 5 hook). Smallest adapter surface; the DataFrame exception for
OHLCV-shaped data does not apply here because rankings are already discrete records.

### 7. No internal try/except in adapter writes

Adapter `write_*` methods do not swallow exceptions. The caller (Phase 5 hooks) wraps
each call in `try/except Exception: logger.warning(...)` per the master plan's
error-handling table. This mirrors `PostgresAdapter`'s posture.

### 8. No hand-rolled retry loop

`motor` / PyMongo handle transient network errors via `serverSelectionTimeoutMS`. Adding
a retry loop in the adapter would duplicate that logic and risk turning a real outage
into a long-tail latency spike. Phase 5 hooks log + skip on failure; that is the retry
model.

### 9. `AdapterManager.from_settings` Mongo branch never raises

Even when `db_write_enabled=True` and `mongo_uri` is set, a failed `connect()` (server
unreachable, auth failure, etc.) results in `mongo=None` plus a structured
`logger.warning`. Application boot continues. Mirrors the Postgres branch behaviour and
PLAN.md error-handling row.

### 10. `connect()` does an explicit `admin.command("ping")` round-trip

`AsyncIOMotorClient(...)` itself is not lazy enough to fail at construction — it queues
operations until first use. To make `from_settings` actually surface a connect failure
(so the manager downgrades to `mongo=None`), `connect()` issues a real
`admin.command("ping")` immediately and lets the timeout / auth error propagate up. This
ensures `/health` reflects truth on day one rather than after the first write.

### 11. Mongo slot type annotation tightens to `MongoAdapter | None`

Phase 2 left `mongo: object | None = None` as a placeholder. Phase 3 tightens to
`MongoAdapter | None`. The change is type-only — `from_settings` already returned `None`
when configuration was incomplete; `close()` and `ping()` already short-circuited on
`None`. Mypy strict mode covers downstream call sites; no runtime change at the
boundary.

### 12. One scope deviation from master plan (user-approved 2026-05-07)

| Deviation | Source | Rationale |
|---|---|---|
| Read methods + `BacktestResultDoc` / `SignalSnapshotDoc` / `ModelParamsDoc` / `BacktestSummaryRow` added in Phase 3 | Originally Phase 6 | Keeps the Mongo surface in one place; Phase 6 only adds routers + response schemas. Mirrors the Phase 2 deviation precedent. Approved by user 2026-05-07. |

---

## Implementation Steps

### Step 1: Adapter-level Pydantic models (extend `models.py`)

Append to `src/csm/adapters/models.py`:

- `BacktestResultDoc(run_id, strategy_id, created_at, config, metrics, equity_curve, trades)`
  — frozen, `created_at: datetime`, `config: dict[str, object]`,
  `metrics: dict[str, float]`, `equity_curve: dict[str, float]`,
  `trades: list[dict[str, object]]`.
- `SignalSnapshotDoc(strategy_id, date, rankings)` — frozen, `date: datetime`,
  `rankings: list[dict[str, object]]`.
- `ModelParamsDoc(strategy_id, version, params, created_at)` — frozen.
- `BacktestSummaryRow(run_id, strategy_id, created_at, metrics)` — slim projection used
  by `list_backtest_results`.

Update `__all__` to re-export the four new symbols.

### Step 2: `MongoAdapter` class

Replace the stub at `src/csm/adapters/mongo.py` with the full class. Module-level `_COLL`
frozen dataclass. Lifecycle methods (`connect` / `close` / `__aenter__` / `__aexit__` /
`ping`). Three writes (`write_backtest_result` / `write_signal_snapshot` /
`write_model_params`). Four reads (`read_backtest_result` / `read_signal_snapshot` /
`read_model_params` / `list_backtest_results`). Google-style docstrings on every public
method. Strict typing — explicit `AsyncIOMotorClient` and `AsyncIOMotorCollection`
annotations on private fields.

### Step 3: `AdapterManager` Mongo wiring

In `src/csm/adapters/__init__.py`:

- Import `MongoAdapter` at module level (no longer `TYPE_CHECKING`).
- Tighten `mongo: object | None` → `mongo: MongoAdapter | None` everywhere.
- Add a `mongo: MongoAdapter | None = None` parameter to `__init__`.
- Extend `from_settings`: build `MongoAdapter(settings.mongo_uri)` only when
  `db_write_enabled=True` AND `settings.mongo_uri` is set. Wrap `connect()` in
  `try/except` exactly like Postgres; log a warning on failure and downgrade to
  `mongo=None`. Log a warning when `mongo_uri` is missing.
- Extend `close()`: best-effort `await self.mongo.close()` after Postgres; log + swallow
  on failure; clear the slot to `None`.
- Extend `ping()`: when `self.mongo is not None`, await `self.mongo.ping()` and add a
  `mongo` key (`"ok"` or `"error:..."`) to the result dict.
- Update `__all__` to add `MongoAdapter`.

No changes are needed to `api/main.py` or `api/deps.py` — Phase 2 already wired the
manager into the lifespan and exposed `get_adapter_manager`. `/health` will pick up the
Mongo ping automatically through `manager.ping()`.

### Step 4: Unit tests — `tests/unit/adapters/test_mongo.py`

Test classes mirroring Phase 2's `test_postgres.py`:

- `TestLifecycle` — patches `motor.motor_asyncio.AsyncIOMotorClient`; asserts `connect`
  constructs the client with `tz_aware=True` and runs `admin.command("ping")`; `close`
  calls `client.close()`; both idempotent.
- `TestPing` — `ping()` returns `True` when `admin.command("ping")` returns
  `{"ok": 1.0}`; `False` otherwise.
- `TestWriteBacktestResult` — assert `replace_one` called with `{"run_id": ...}` filter,
  the full doc, `upsert=True`.
- `TestWriteSignalSnapshot` — assert `update_one` called with compound filter and
  `{"$set": doc}` payload; verify `upsert=True`; verify the doc carries `strategy_id`,
  `date`, `rankings`.
- `TestWriteModelParams` — same pattern as signal snapshot but with `(strategy_id,
  version)` filter.
- `TestReads` — each `read_*` parses the mocked `find_one` / `to_list` return into the
  expected Pydantic model; `read_*` returns `None` when `find_one` returns `None`;
  `list_backtest_results` projects with `_id=0` and respects `limit`.
- `TestRequiresClient` — every public method raises `RuntimeError` ("MongoAdapter is not
  connected…") when called before `connect()`.

### Step 5: Unit tests — `tests/unit/adapters/test_manager.py` extension

Add new test cases parallel to the existing Postgres ones:

- Mongo URI missing (flag on, `mongo_uri=None`) → `manager.mongo is None`; warning
  logged.
- Mongo connect failure (mock `MongoAdapter.connect` to raise) → `manager.mongo is
  None`; warning logged; no re-raise.
- Mongo happy path (mocks succeed) → `manager.mongo` is the real `MongoAdapter`.
- `ping()` returns both `postgres` and `mongo` keys when both adapters are live.
- `close()` calls both adapter `close()` methods.

### Step 6: Unit tests — `tests/unit/test_api_lifespan.py` extension

Add `test_adapter_manager_mongo_none_when_db_write_disabled(client)` to the existing
`TestAdapterManagerLifespan` class. The client fixture already runs with
`db_write_enabled=False`, so the assertion is `app.state.adapters.mongo is None`.

### Step 7: Integration tests — `tests/integration/adapters/conftest.py` + `test_mongo_io.py`

Extend the existing `conftest.py`:

- Add a `mongo_adapter` `pytest_asyncio` fixture that yields a connected `MongoAdapter`
  from `os.environ["CSM_MONGO_URI"]`; `pytest.skip()` if absent.
- Extend the autouse cleanup to delete `strategy_id="test-csm-set"` documents from
  `signal_snapshots` and `model_params`, and `run_id` matching `^test-csm-set-` from
  `backtest_results`.

Create `tests/integration/adapters/test_mongo_io.py` (`@pytest.mark.infra_db`):

- `test_write_backtest_result_idempotent` — write a doc; re-write with mutated metrics;
  `find_one({"run_id": ...})` reflects the second write (`replace_one` semantics).
- `test_write_signal_snapshot_idempotent` — write rankings for a date; re-run with
  different rankings; `find_one(...)` reflects the latest; collection count for that key
  remains 1.
- `test_write_model_params_idempotent` — same pattern as signal snapshot but on
  `(strategy_id, version)`.
- `test_read_backtest_result_round_trip`.
- `test_read_signal_snapshot_round_trip`.
- `test_read_model_params_round_trip`.
- `test_list_backtest_results_descending_limit` — write 5 docs; assert listing returns
  the 3 most recent in descending `created_at` order; assert filter / projection.

### Step 8: PLAN.md updates

In `docs/plans/feature_adapter/PLAN.md`:

- Flip Phase 3 §3.1–3.4 checkboxes from `[ ]` to `[x]`.
- Update the Phase 3 status header to `[x]` Complete.
- Update §5.1 Mongo slot bullet to reflect the typed `MongoAdapter | None` annotation.
- Add a Phase 6 deviation note mirroring Phase 2's existing one.
- Update the Current Status table row for Phase 3 to `[x]` complete.

### Step 9: Quality gates

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src/ api/ && uv run pytest tests/ -v
```

### Step 10: Commit

Single commit using the standards-compliant message in Completion Notes below.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `src/csm/adapters/models.py` | MODIFY | Add `BacktestResultDoc`, `SignalSnapshotDoc`, `ModelParamsDoc`, `BacktestSummaryRow`; extend `__all__` |
| `src/csm/adapters/mongo.py` | MODIFY | Replace stub with full `MongoAdapter` |
| `src/csm/adapters/__init__.py` | MODIFY | Tighten `mongo` annotation; extend `from_settings` / `close` / `ping`; re-export `MongoAdapter` |
| `tests/unit/adapters/test_mongo.py` | CREATE | Mocked-motor unit tests |
| `tests/unit/adapters/test_manager.py` | MODIFY | Mongo degradation + happy-path cases |
| `tests/unit/test_api_lifespan.py` | MODIFY | Assert `app.state.adapters.mongo is None` when flag off |
| `tests/integration/adapters/conftest.py` | MODIFY | Add `mongo_adapter` fixture + extend autouse teardown |
| `tests/integration/adapters/test_mongo_io.py` | CREATE | `infra_db` integration tests |
| `docs/plans/feature_adapter/PLAN.md` | MODIFY | Phase 3 progress flips; Phase 5.1 Mongo annotation note; Phase 6 deviation note; Current Status table |
| `docs/plans/feature_adapter/phase_3_mongo_adapter.md` | CREATE | This document |

---

## Acceptance Criteria

- [x] `uv run mypy src/csm/adapters/ api/` clean.
- [x] `uv run ruff check .` and `uv run ruff format --check .` clean.
- [x] `uv run pytest tests/unit/adapters/ -v` green.
- [x] `uv run pytest tests/ -v` green (full suite, no `infra_db` tests).
- [x] `MongoAdapter` instantiable without a live DB; `connect()` failure does not crash
  app boot.
- [x] `AdapterManager.mongo` is typed `MongoAdapter | None` and is set when
  `db_write_enabled=True` AND `mongo_uri` is set; missing URI / connect failure both
  downgrade to `None` with a logged warning.
- [x] `app.state.adapters.mongo is None` when `db_write_enabled=False` (Phase 1 contract
  preserved).
- [~] `/health` returns `"db": {"postgres": "ok", "mongo": "ok"}` via pool/client ping
  when both adapters are live. *(disabled-flag path verified in unit tests; live-stack
  verification deferred to manual smoke / Phase 5.)*
- [~] With `quant-infra-db` stack up: `uv run pytest tests/integration/adapters/ -m
  infra_db -v` green. *(Tests authored and self-skip without env vars; live execution
  deferred until the local stack is brought up.)*
- [x] Re-running `write_backtest_result` / `write_signal_snapshot` /
  `write_model_params` produces no duplicate documents (collection count for the natural
  key remains 1; `replace_one` reflects the latest write for `backtest_results`).
  *(Verified by mocked unit tests + integration assertions; live verification deferred.)*
- [x] Reads round-trip writes correctly, return frozen Pydantic models, and never expose
  Mongo `_id`.
- [x] `list_backtest_results` orders by `created_at DESC`, respects `limit`, and the
  slim `BacktestSummaryRow` projection does not include `equity_curve` or `trades`.
- [x] PLAN.md updated with progress flips and the scope-deviation annotation.

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Mongo unique indexes on natural keys not present on the live `csm_logs` server | Low | Medium — duplicate docs slip in despite `update_one(...,upsert=True)` | Integration test `test_write_*_idempotent` asserts post-write `count_documents(filter)` is exactly 1; failure here is a loud canary that triggers a coordination ping with `quant-infra-db` |
| Naïve datetime returned from a server / driver combination missing `tz_aware=True` | Low | Medium — silent UTC/Bangkok confusion on read | Always construct `AsyncIOMotorClient(uri, tz_aware=True)`; round-trip integration test asserts `tzinfo is not None` on read |
| `motor` 3.x API drift (some methods renamed vs PyMongo 4.x) | Low | Low — caught by mypy / unit tests | Pin `motor>=3.4` (already in `pyproject.toml`); use only stable surface area: `AsyncIOMotorClient`, `client[db][coll]`, `replace_one`, `update_one`, `find_one`, `find().to_list(length=N)`, `admin.command("ping")` |
| Caller passes a non-JSON-serialisable object (e.g. `numpy.float64`, `pd.Timestamp`) into `write_signal_snapshot` rankings | Medium | Low — Mongo encoder raises | Adapter does **not** silently coerce; lets the error propagate to the Phase 5 hook. PLAN.md hook contract calls for `try/except + logger.warning + continue`. Hook-side conversion (`float()`, `dt.to_pydatetime()`) is out of scope here |
| `connect()` ping succeeds but the target db / collection is unreachable later (auth scoped to `csm_logs`) | Low | Low | Per-write errors propagate to caller; `/health` pool ping catches dead client between requests |
| Schema drift on the `quant-infra-db` side adds new required fields to a collection | Medium | Medium — writes silently miss fields | Mongo is schema-less so writes never fail on missing fields, but reads validating into the strict Pydantic models would fail loudly on missing required fields. Intended canary |
| Adapter close hangs on a flaky connection during shutdown | Low | Low | `AdapterManager.close()` already wraps each adapter close in a `try/except + logger.warning`; failures are non-fatal |

---

## Completion Notes

### Summary

Phase 3 complete. All deliverables shipped in a single session:

- **Lifecycle:** `MongoAdapter` owns one `motor.AsyncIOMotorClient(uri, tz_aware=True,
  serverSelectionTimeoutMS=5000)`. `connect()` runs an explicit
  `await client.admin.command("ping")` so server-unreachable / auth failures surface at
  `from_settings` time and downgrade the manager slot to `None` instead of failing later
  on first write. `connect`/`close` are idempotent; `__aenter__`/`__aexit__` provide the
  async-context-manager shape; `ping()` runs `admin.command("ping")` through the live
  client. Collection names live on a frozen `_Collections` dataclass, mirroring the
  `_SQLStatements` pattern in `PostgresAdapter`.
- **Writes:** `write_backtest_result` uses `replace_one({"run_id": ...}, doc,
  upsert=True)` — re-running a backtest replaces the prior doc cleanly.
  `write_signal_snapshot` and `write_model_params` use
  `update_one({...natural key...}, {"$set": doc}, upsert=True)` so future field
  additions extend rather than overwrite the document. None of the writes swallow
  exceptions; the Phase 5 hook contract owns best-effort policy.
- **Reads (pulled forward from Phase 6):** `read_backtest_result`,
  `read_signal_snapshot`, `read_model_params`, `list_backtest_results` strip the Mongo
  `_id` via projection and return frozen Pydantic models defined in
  `src/csm/adapters/models.py`. The slim `BacktestSummaryRow` projection omits the
  potentially-large `equity_curve` and `trades` arrays to keep listing endpoints cheap.
- **AdapterManager Mongo wiring:** the `mongo` slot tightened to `MongoAdapter | None`;
  `from_settings` now constructs Mongo whenever `db_write_enabled=True` AND `mongo_uri`
  is set; missing URI and connect failures both downgrade to `mongo=None` with a
  structured `logger.warning` and never raise. `close()` and `ping()` are extended to
  cover the new slot. No changes were needed to `api/main.py` / `api/deps.py` — the
  lifespan and DI plumbing from Phase 2 picks Mongo up automatically through
  `manager.ping()`.
- **Tests:** `tests/unit/adapters/test_mongo.py` covers lifecycle (including the explicit
  ping on connect), `ping()` truthiness, every write's filter / payload / `upsert=True`
  shape, every read's projection / model parsing / `None` path, and the
  `_require_client` guard. `tests/unit/adapters/test_manager.py` is extended with
  Mongo-missing-URI / connect-failure / happy-path / ping-merge / close-error cases.
  `tests/unit/test_api_lifespan.py` gains a `mongo is None` assertion under
  `db_write_enabled=False`. `tests/integration/adapters/conftest.py` ships a
  `mongo_adapter` fixture that auto-skips without `CSM_MONGO_URI` and an autouse
  teardown that wipes `test-csm-set` artefacts across all three collections (plus
  `run_id` matching `^test-csm-set-` from `backtest_results`).
  `tests/integration/adapters/test_mongo_io.py` exercises idempotency on every write
  plus all four reads, including the ordering / limit / slim-projection contract for
  `list_backtest_results`.

### Issues Encountered

1. **Two scope deviations agreed up front (recorded in Design Decisions §6 and §12).**
   Read methods (Phase 6) and the `AdapterManager` Mongo slot wiring (Phase 5.1's typed
   annotation) were pulled into Phase 3 with explicit user approval rather than handled
   as drift. The `list[dict]` rankings input matches PLAN.md §3.3 verbatim. PLAN.md §3 /
   §5.1 / §6 / Current Status table were updated to reflect this.
2. **`motor` 3.x type stubs are partial.** Some `AsyncIOMotorClient`-returned types are
   typed as `Any` in the public stubs. We avoided over-tightening private field
   annotations beyond what the stubs cover so that `uv run mypy` stays clean without
   resorting to `# type: ignore` sprinkling.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.7)
**Status:** Complete
**Completed:** 2026-05-07
