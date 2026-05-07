# Phase 6: API History Endpoints

**Feature:** csm-set-adapter — Integration layer connecting csm-set to quant-infra-db
**Branch:** `feature/csm-set-adapter`
**Created:** 2026-05-07
**Status:** Complete
**Completed:** 2026-05-07
**Depends On:** Phase 1 (Complete), Phase 2 (Complete — read methods + AdapterManager skeleton),
Phase 3 (Complete — Mongo read methods), Phase 4 (Complete — Gateway read methods),
Phase 5 (Complete — pipeline hooks)

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Endpoint Surface](#endpoint-surface)
6. [Implementation Steps](#implementation-steps)
7. [File Changes](#file-changes)
8. [Acceptance Criteria](#acceptance-criteria)
9. [Risks & Mitigations](#risks--mitigations)
10. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 6 ships the private-mode REST surface (`/api/v1/history/*`) that exposes
the central-DB time series accumulated by Phases 2–5. After this phase, an
external API Gateway / dashboard / future broker bridge can fetch csm-set
history (equity curves, trades, daily performance, portfolio snapshots,
backtest summaries, signal snapshots) over HTTP without touching the local
Parquet store.

The heavy lifting was already done in Phases 2–4: the underlying read methods
(`PostgresAdapter.read_equity_curve`, `read_trade_history`, `read_backtest_log`;
`MongoAdapter.read_signal_snapshot`, `list_backtest_results`,
`read_backtest_result`, `read_model_params`; `GatewayAdapter.read_daily_performance`,
`read_portfolio_snapshots`) and their frozen Pydantic v2 result models live
in [src/csm/adapters/](../../src/csm/adapters/). Phase 6 only adds the routers,
response schemas, conditional mount, and APIKey gating on top.

### Parent Plan Reference

- [docs/plans/feature_adapter/PLAN.md](PLAN.md) — Master plan, Phase 6 section
  (lines 593–633).

### Key Deliverables

1. **`api/routers/history.py`** — Six async GET endpoints with a uniform 503
   helper. Reuses adapter read methods directly.
2. **`api/schemas/history.py`** — Re-exports the adapter models under
   `api.schemas.history` for router-local OpenAPI clarity. Also defines the
   `Strategy` query-param type alias (default `"csm-set"`).
3. **`api/main.py`** — Always-on `include_router` plus a new
   `PRIVATE_ONLY_PREFIXES` tuple wired into `public_mode_guard`. Public-mode
   requests to `/api/v1/history/*` get a 403 RFC 7807 problem detail (matching
   the existing convention for write paths). The middleware reads the live
   ``settings`` module attribute on every request, so test fixtures that
   toggle public/private mode keep working without re-importing the app.
4. **`api/security.py`** — New `PROTECTED_PREFIXES` set with
   `"/api/v1/history/"`, plus an extra branch in `is_protected_path`. Keeps
   existing exact-match contract for write paths intact.
5. **`tests/unit/api/test_history.py`** — Per-endpoint coverage: happy path
   (with stubbed adapters on `app.state.adapters`), 503 path (default
   `db_write_enabled=False`), 404 path for `/signals`, public-mode
   not-mounted, auth-required.
6. **`tests/unit/test_api_security.py`** — Cover the new prefix branch.
7. **`tests/integration/adapters/test_history_api.py`** — `infra_db`-marked
   end-to-end round-trips: write via adapter, fetch via TestClient, assert
   shape and ordering. Skips cleanly when DSNs are unset.
8. **PLAN.md** — Phase 6 progress flips and Current Status update.

---

## AI Prompt

The following prompt was used to generate this phase:

```
You are tasked with implementing Phase 6 — API History Endpoints for the csm-set
project. Follow these steps precisely:

1. Preparation
   - Carefully read .claude/knowledge/project-skill.md and
     .claude/playbooks/feature-development.md to internalize all engineering
     standards and workflow expectations.
   - Review docs/plans/feature_adapter/PLAN.md, focusing on the Phase 6 section,
     and ensure you understand all deliverables, acceptance criteria, and
     architectural context.
   - Review docs/plans/feature_adapter/phase_5_pipeline_integration.md for the
     current state and prior implementation details.

2. Planning
   - Draft a detailed implementation plan for Phase 6 in markdown, using the
     format from docs/plans/examples/phase1-sample.md.
   - Your plan must include: scope, deliverables, acceptance criteria, risks,
     and the full AI agent prompt (this prompt).
   - Save the plan as docs/plans/feature_adapter/phase_6_api_history_endpoints.md.

3. Implementation
   - Only begin coding after the plan is complete and saved.
   - Implement all deliverables for Phase 6:
     - Expose async API endpoints for retrieving historical equity curves,
       signal snapshots, daily performance, portfolio snapshots, backtest
       logs/results, and trade history from the central databases.
     - Ensure all code follows project standards: type safety, async/await,
       Pydantic validation, error handling, and import organization.
     - Add or update comprehensive unit and integration tests.
     - Update and extend documentation as needed.

4. Documentation and Progress Tracking
   - Update docs/plans/feature_adapter/PLAN.md and
     docs/plans/feature_adapter/phase_6_api_history_endpoints.md with progress
     notes, completion status, and any issues encountered.
   - Mark acceptance criteria as completed or note any deviations.

5. Commit and Finalization
   - Commit all changes in a single commit with a clear, standards-compliant
     message summarizing the work.
   - Ensure all tests pass and the implementation meets the acceptance criteria.

Files to reference and/or modify:
- .claude/knowledge/project-skill.md
- .claude/playbooks/feature-development.md
- docs/plans/feature_adapter/PLAN.md
- docs/plans/feature_adapter/phase_5_pipeline_integration.md
- docs/plans/examples/phase1-sample.md
- Target plan file: docs/plans/feature_adapter/phase_6_api_history_endpoints.md
- All relevant API, adapter, and model modules

Expected deliverables:
- A new plan markdown file at docs/plans/feature_adapter/phase_6_api_history_endpoints.md
  with the full implementation plan and embedded prompt.
- All Phase 6 deliverables implemented and tested.
- Updated progress/completion notes in both docs/plans/feature_adapter/PLAN.md
  and the new phase plan file.
- A single commit with all changes and a standards-compliant message.

Begin by drafting the plan markdown file. Do not start implementation until the
plan is complete and saved.
```

---

## Scope

### In Scope (Phase 6)

| Component | Description | Status |
|---|---|---|
| `api/routers/history.py` | Six GET endpoints + uniform 503 helper | `[x]` |
| `api/schemas/history.py` | Re-export adapter models under `api.schemas.history` | `[x]` |
| `api/main.py` mount | Always-on `include_router` + `PRIVATE_ONLY_PREFIXES` in `public_mode_guard` | `[x]` |
| `api/security.py` | `PROTECTED_PREFIXES` + prefix branch in `is_protected_path` | `[x]` |
| `tests/integration/test_api_history.py` | Happy / 503 / 404 / public-mode-403 / auth tests | `[x]` |
| `tests/unit/test_api_security.py` | Coverage for new prefix branch | `[x]` |
| `tests/integration/adapters/test_history_api.py` | `infra_db` round-trips | `[x]` |
| `pyproject.toml` | Pytest `--import-mode=importlib` to fix pre-existing `test_pipeline.py` collision | `[x]` |
| `docs/plans/feature_adapter/PLAN.md` | Phase 6 progress flips; Current Status update | `[x]` |

### Out of Scope (Phase 6)

- Single-resource endpoints `GET /backtests/{run_id}` (full doc) and
  `GET /model-params/{strategy_id}/{version}` — adapter reads exist but PLAN.md
  Phase 6 does not require the routes. Defer to a follow-up.
- Pagination / cursor wrappers — single-strategy volumes don't justify it
  yet (see PLAN.md "Out of scope" §Overview).
- Public-mode exposure — write-back stays private; reads also private.
- Read-side caching — defer.
- Coverage gate enforcement / CI workflow — Phase 7.

---

## Design Decisions

### 1. Reuse adapter models directly as `response_model`

The Phase 2–4 models (`EquityPoint`, `TradeRow`, `BacktestSummaryRow`,
`SignalSnapshotDoc`, `DailyPerformanceRow`, `PortfolioSnapshotRow`) are
already frozen Pydantic v2 with full field annotations and serialise cleanly
to JSON. Wrapping them in identical "API schemas" would be busywork. Instead,
[api/schemas/history.py](../../api/schemas/history.py) re-exports them so:

- Router code can import its response types from `api.schemas.history`
  (router-local convention, mirrors `api.schemas.health`).
- Future view-level wrapping (pagination metadata, deprecation hints, etc.)
  can be added in `api/schemas/history.py` without touching `csm.adapters`.

### 2. Single 503 helper per router module

```python
def _require(adapter: object | None, name: str) -> object:
    if adapter is None:
        raise HTTPException(
            status_code=503,
            detail=f"{name} adapter unavailable (db_write_enabled is false or DSN missing).",
        )
    return adapter
```

Keeps each handler one or two lines of guard plus a single `await`. The 503
detail is uniform across endpoints, which makes it easy to test once and
trust the rest. The helper is `cast`-typed at the call site rather than
generic-typed so we don't fight mypy with type-vars.

### 3. Conditional mount on private mode

The history surface is a private-mode-only feature. Mounting it
unconditionally would be wrong in two ways:

- Public-mode boots would expose history endpoints that, by design, hit
  databases the public deployment cannot reach.
- The existing `public_mode_guard` middleware filters by exact path;
  extending it to a prefix would couple it to history concerns it should
  not own.

Solution: in [api/main.py](../../api/main.py), inside the `include_router`
block, wrap the history mount in `if not settings.public_mode:`. Public mode
returns `404 Not Found` for `/api/v1/history/*` because the route doesn't
exist — the cleanest possible answer.

### 4. APIKey gating via `PROTECTED_PREFIXES`

`is_protected_path` currently exact-matches `PROTECTED_PATHS` and protects
"any non-GET under `/api/v1/`". History reads are GETs, so they would slip
past. The minimal extension:

```python
PROTECTED_PREFIXES: frozenset[str] = frozenset({"/api/v1/history/"})

def is_protected_path(method: str, path: str) -> bool:
    if path in PROTECTED_PATHS:
        return True
    if any(path.startswith(p) for p in PROTECTED_PREFIXES):
        return True
    return method != "GET" and path.startswith("/api/v1/")
```

One extra boolean check per request. Future read surfaces that need auth can
register their prefix without further code changes.

### 5. Date query param promoted to UTC midnight

`/api/v1/history/signals?date=YYYY-MM-DD` accepts a `datetime.date`. Inside
the handler we promote to a UTC-midnight `datetime` before calling
`MongoAdapter.read_signal_snapshot`, which keys on `(strategy_id, date)` as a
tz-aware `datetime`. The OpenAPI summary documents that the day boundary is
UTC, matching the project-wide tz convention (storage in UTC, display in
`Asia/Bangkok`).

### 6. 404 only for single-resource `/signals`

`/signals` is the only single-resource endpoint — it returns `None` from the
adapter when the document is missing. We map that to `HTTPException(404)`.
List endpoints return `200 []` for empty queries; 503 is reserved for
"adapter slot is `None`" (i.e., DB write-back disabled or DSN missing).

### 7. Bounded query params

| Param | Bounds | Default |
|---|---|---|
| `days` | `Query(default=DEFAULT, ge=1, le=3650)` | 90 (or 30 for performance / portfolio per PLAN.md) |
| `limit` | `Query(default=DEFAULT, ge=1, le=1000)` | 100 (trades) / 50 (backtests) |

Bounded ranges prevent accidental DoS (`?days=999999`) and document the
practical envelope in OpenAPI.

### 8. Errors propagate to global handler

Adapter exceptions mid-request (network blip, schema drift) propagate to
the FastAPI global exception handler in [api/errors.py](../../api/errors.py)
which converts to RFC 7807. Routers do **not** catch-and-mask — that is the
existing project posture. Pipeline hooks (Phase 5) catch and warn because
they run in background event loops; request handlers are different — let the
client see the failure.

---

## Endpoint Surface

| Method/path | Adapter call | Response | 503 trigger | 404 trigger |
|---|---|---|---|---|
| `GET /api/v1/history/equity-curve?strategy_id=csm-set&days=90` | `postgres.read_equity_curve` | `list[EquityPoint]` | `manager.postgres is None` | — |
| `GET /api/v1/history/trades?strategy_id=csm-set&limit=100` | `postgres.read_trade_history` | `list[TradeRow]` | `manager.postgres is None` | — |
| `GET /api/v1/history/performance?strategy_id=csm-set&days=30` | `gateway.read_daily_performance` | `list[DailyPerformanceRow]` | `manager.gateway is None` | — |
| `GET /api/v1/history/portfolio-snapshots?days=30` | `gateway.read_portfolio_snapshots` | `list[PortfolioSnapshotRow]` | `manager.gateway is None` | — |
| `GET /api/v1/history/backtests?strategy_id=csm-set&limit=50` | `mongo.list_backtest_results` | `list[BacktestSummaryRow]` | `manager.mongo is None` | — |
| `GET /api/v1/history/signals?strategy_id=csm-set&date=YYYY-MM-DD` | `mongo.read_signal_snapshot` | `SignalSnapshotDoc` | `manager.mongo is None` | adapter returns `None` |

All endpoints are auth-protected via the new `PROTECTED_PREFIXES` and only
mounted in private mode.

---

## Implementation Steps

### Step 1: Create `api/schemas/history.py`

Re-export the adapter models. No new logic.

```python
"""API response schemas for /api/v1/history/* — re-exports from csm.adapters.models."""

from __future__ import annotations

from csm.adapters.models import (
    BacktestSummaryRow,
    DailyPerformanceRow,
    EquityPoint,
    PortfolioSnapshotRow,
    SignalSnapshotDoc,
    TradeRow,
)

DEFAULT_STRATEGY_ID: str = "csm-set"

__all__: list[str] = [
    "DEFAULT_STRATEGY_ID",
    "BacktestSummaryRow",
    "DailyPerformanceRow",
    "EquityPoint",
    "PortfolioSnapshotRow",
    "SignalSnapshotDoc",
    "TradeRow",
]
```

### Step 2: Create `api/routers/history.py`

Six handlers, each one-liner over the adapter. Uniform `_require` 503 helper
at the top. `responses=` blocks document 503 (and 404 for `/signals`).
Routes use the kebab-case PLAN.md spec.

### Step 3: Modify `api/security.py`

Add `PROTECTED_PREFIXES` and the new branch in `is_protected_path`.

### Step 4: Modify `api/main.py`

Conditional `include_router` block:

```python
if not settings.public_mode:
    from api.routers.history import router as history_router

    app.include_router(history_router, prefix="/api/v1")
```

Place after the unconditional includes so it appears with its sibling routers
in OpenAPI.

### Step 5: Tests

**Unit** — [tests/unit/api/test_history.py](../../tests/unit/api/test_history.py):

| Test class | What it verifies |
|---|---|
| `TestPublicModeNoMount` | `client.get("/api/v1/history/equity-curve")` returns 404 in public mode |
| `TestEquityCurve503` | Default `private_client_with_key` (no DSNs) → 503 with detail "postgres adapter unavailable…" |
| `TestEquityCurveHappy` | Stub `app.state.adapters.postgres` with a `MagicMock` returning `[EquityPoint(...)]`; assert response body |
| `TestTrades503` / `TestTradesHappy` | Same shape for `/trades` |
| `TestPerformance503` / `TestPerformanceHappy` | Stub `app.state.adapters.gateway` |
| `TestPortfolioSnapshots503` / `TestPortfolioSnapshotsHappy` | Same |
| `TestBacktests503` / `TestBacktestsHappy` | Stub `app.state.adapters.mongo` |
| `TestSignals503` / `TestSignals404` / `TestSignalsHappy` | Adapter returns `None` → 404; doc → 200 |
| `TestAuthRequired` | GET to `/api/v1/history/equity-curve` without `X-API-Key` → 401 |

**Unit** — extend [tests/unit/test_api_security.py](../../tests/unit/test_api_security.py)
with one parametrised test asserting any `/api/v1/history/<x>` path is
protected for both GET and POST.

**Integration** — [tests/integration/adapters/test_history_api.py](../../tests/integration/adapters/test_history_api.py),
`pytestmark = pytest.mark.infra_db`. Spin up a TestClient in private mode
with `CSM_API_KEY` set; replace `app.state.adapters` with the
`adapter_manager` fixture; for each endpoint write rows via the adapter,
fetch via TestClient, assert response shape.

### Step 6: Quality gates

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src/ api/ && uv run pytest tests/ -v
```

### Step 7: PLAN.md updates

- Mark Phase 6 items 6.1–6.3 as `[x]`.
- Update Phase 6 status header to `[x]` Complete.
- Update Current Status table row.

### Step 8: Commit

```
feat(api): add /api/v1/history/* private-mode endpoints (Phase 6)

- equity-curve / trades / performance / portfolio-snapshots / backtests / signals
- Pydantic v2 response schemas reuse adapter models
- 503 when adapters unavailable; 404 for missing signal snapshot
- API-key protected via new PROTECTED_PREFIXES; private mode only
- Unit + infra_db integration tests; PLAN.md + phase doc updated
```

---

## File Changes

| File | Action | Description |
|---|---|---|
| `api/routers/history.py` | CREATE | Six GET endpoints + 503 helper |
| `api/schemas/history.py` | CREATE | Re-export adapter models for router-local OpenAPI |
| `api/main.py` | MODIFY | Conditional `include_router` in private mode |
| `api/security.py` | MODIFY | `PROTECTED_PREFIXES` + prefix check |
| `tests/unit/api/test_history.py` | CREATE | Per-endpoint happy / 503 / 404 / auth tests |
| `tests/unit/test_api_security.py` | MODIFY | Cover the new prefix branch |
| `tests/integration/adapters/test_history_api.py` | CREATE | `infra_db` round-trips |
| `docs/plans/feature_adapter/PLAN.md` | MODIFY | Phase 6 progress flips; Current Status update |
| `docs/plans/feature_adapter/phase_6_api_history_endpoints.md` | CREATE | This document |

---

## Acceptance Criteria

- [x] `uv run ruff check .` clean.
- [x] `uv run ruff format --check .` clean.
- [x] `uv run mypy src/ api/` clean.
- [x] `uv run pytest tests/ -v` green: 1005 passed, 36 skipped (`infra_db`).
- [x] All six endpoints return their declared `response_model` shape on
  happy path (verified via `tests/integration/test_api_history.py`).
- [x] Each endpoint returns HTTP 503 when its corresponding adapter slot is
  `None`.
- [x] `/signals` returns HTTP 404 when the snapshot document is missing.
- [x] Public-mode `GET /api/v1/history/equity-curve` returns 403 with
  RFC 7807 detail "Disabled in public mode" (deviation from plan: route is
  always-mounted; public mode is denied at the middleware layer rather than
  via not-mounted-404, which doesn't survive the test app singleton).
- [x] Private-mode + `CSM_API_KEY` set + missing/invalid `X-API-Key` →
  401 RFC 7807 problem detail.
- [~] `tests/integration/adapters/test_history_api.py` self-skips when DSNs
  unset (verified). Live verification deferred to a quant-infra-db-up run.
- [x] PLAN.md Phase 6 marked Complete; Current Status table updated.

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `date` query param tz ambiguity for `/signals` | Medium | Low | Promote `date` → UTC midnight inside the handler; document in OpenAPI summary |
| 503 vs 200-with-empty-list confusion when adapter is live but no rows exist | Low | Low | Adapter returns `[]`; handler returns `200 []`. 503 reserved for adapter slot `None` — documented per endpoint |
| Prefix gating accidentally breaks existing GETs | Low | Medium | Keep `PROTECTED_PREFIXES` narrow (`"/api/v1/history/"`); add explicit unit coverage; rerun full security test module |
| Adapter raises mid-request (network blip) | Medium | Low | Let FastAPI global handler convert to RFC 7807; do not catch-and-mask. Matches existing posture |
| TestClient lifespan creates `AdapterManager` from env DSNs that are accidentally set | Low | Low | Unit-test fixtures don't set DSNs; integration tests explicitly inject via `adapter_manager` fixture |
| `BacktestSummaryRow.metrics` JSON shape varies | Low | Low | Field is typed `dict[str, float]`; the adapter coerces |

---

## Completion Notes

### Summary

Phase 6 complete. All deliverables shipped in a single session:

- **Router** (`api/routers/history.py`): six async GETs — `/equity-curve`,
  `/trades`, `/performance`, `/portfolio-snapshots`, `/backtests`, `/signals`
  — each one-liner over the corresponding adapter read method. Uniform
  `_require` helper raises `HTTPException(503)` when the adapter slot is
  `None`. `/signals` raises `HTTPException(404)` when the adapter returns
  `None` and promotes the `date` query param to UTC midnight before lookup.
  Bounded query params (`days` 1–3650, `limit` 1–1000) with sensible
  defaults that match the PLAN.md spec.
- **Schemas** (`api/schemas/history.py`): thin re-export of the Phase 2–4
  frozen Pydantic v2 adapter models for router-local OpenAPI clarity. No
  duplicate model definitions.
- **Mount + guard** (`api/main.py`): the history router is registered
  unconditionally; `public_mode_guard` was extended with `PRIVATE_ONLY_PREFIXES`
  so requests under `/api/v1/history/*` are 403'd in public mode (matches
  the convention used by write paths). The router-only-in-private-mode
  approach in the original plan was abandoned because FastAPI evaluates
  `app.include_router` once at import time, which the test fixtures (which
  toggle public/private mode after import) cannot influence.
- **Auth gating** (`api/security.py`): added `PROTECTED_PREFIXES = {"/api/v1/history/"}`
  with a one-line branch in `is_protected_path`. APIKeyMiddleware protects
  every history GET in private mode without affecting any other path.
- **Tests** — 31 new request/response tests in
  `tests/integration/test_api_history.py` (public-mode 403, missing/invalid
  key 401, adapter-unavailable 503, happy paths with stub adapters, 404
  for missing signal snapshot, 422 for out-of-range query params and bad
  date strings) and 6 `infra_db`-marked end-to-end tests in
  `tests/integration/adapters/test_history_api.py` (write via adapter,
  fetch via TestClient, assert shape and ordering). Existing
  `tests/unit/test_api_security.py` extended with one parametrised test
  for the new prefix branch.
- **Test discovery fix** (`pyproject.toml`): switched pytest to
  `--import-mode=importlib` so `tests/unit/features/test_pipeline.py` and
  `tests/integration/adapters/test_pipeline.py` (introduced in Phase 5)
  can coexist. Without this, `uv run pytest tests/` failed at collection
  on the previous commit. Modern pytest recommendation.
- **OpenAPI snapshot**: regenerated
  `tests/integration/__snapshots__/openapi.json` to include the six new
  endpoints and the updated `/api/v1/history/*` paths.
- **Quality gates**: `ruff check`, `ruff format --check`, `mypy src/ api/`
  all clean; `pytest tests/` reports 1005 passed, 36 skipped (`infra_db`).

### Issues Encountered

1. **App singleton vs fixture toggle.** The original plan had
   `if not settings.public_mode: app.include_router(history_router, ...)`
   in `api/main.py`. This is correct at production runtime but breaks the
   test suite — `client` (public mode) and `private_client_with_key`
   (private mode) share the same `app` instance, and whichever loads first
   freezes the route table. Switched to always-mount + middleware-level
   denial; behaviour at production runtime is identical (public-mode
   requests get a 403 instead of a 404), and the test fixtures now work
   correctly without mutual interference.

2. **Pre-existing `test_pipeline.py` collision (Phase 5).** Phase 5 added
   `tests/integration/adapters/test_pipeline.py`, which collided with the
   long-standing `tests/unit/features/test_pipeline.py` under pytest's
   default `prepend` import mode. The Phase 5 commit didn't catch it
   because its test runs targeted the new directory. Fixed by enabling
   `--import-mode=importlib` in `pyproject.toml`. The fix is minimal,
   project-wide, and matches the modern pytest recommendation.

3. **OpenAPI snapshot drift.** Adding six endpoints changes
   `/openapi.json`; the pinned snapshot test fails until the snapshot is
   regenerated. Standard procedure (documented in the snapshot test's own
   docstring) — regenerated in this commit.

---

**Document Version:** 1.1
**Author:** AI Agent (Claude Opus 4.7)
**Status:** Complete
**Completed:** 2026-05-07
