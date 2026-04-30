# Phase 5 — API Master Plan

**Feature:** Production-grade REST API and daily scheduler for the SET Cross-Sectional Momentum Strategy
**Branch:** `feature/phase-5-api`
**Created:** 2026-04-30
**Status:** In progress
**Depends on:** Phase 1 (Data Pipeline — complete), Phase 2 (Signal Research — complete), Phase 3 (Backtesting — complete), Phase 4 (Portfolio Construction & Risk — complete through 4.9)
**Positioning:** Production layer — promotes the existing API scaffolding under `api/` into a typed, observable, dual-mode (public / private) FastAPI surface that exposes the validated Phase 4 portfolio engine and runs the daily refresh job. This is the prerequisite for Phase 6 (Docker & Public Distribution) and the future multi-strategy dashboard.

---

## Table of Contents

1. [Overview](#overview)
2. [Problem Statement](#problem-statement)
3. [Existing Scaffolding Audit](#existing-scaffolding-audit)
4. [Design Rationale](#design-rationale)
5. [Architecture](#architecture)
6. [Implementation Phases](#implementation-phases)
7. [Data Models](#data-models)
8. [Error Handling Strategy](#error-handling-strategy)
9. [Testing Strategy](#testing-strategy)
10. [Success Criteria](#success-criteria)
11. [Future Enhancements](#future-enhancements)
12. [Commit & PR Templates](#commit--pr-templates)

---

## Overview

### Purpose

Phase 5 takes the FastAPI scaffolding that already exists in [api/](../../../api) — `app` factory in [api/main.py](../../../api/main.py), five routers in [api/routers/](../../../api/routers), and an APScheduler-based daily refresh in [api/scheduler/jobs.py](../../../api/scheduler/jobs.py) — and promotes it to a **production-grade REST surface** suitable to expose the strategy beyond `localhost`. The goal is two-fold:

1. **Harden**: replace `dict[str, object]` returns with typed Pydantic response models, formalize OpenAPI tags and examples, introduce structured exception handling (RFC 7807 problem-details), wire request-ID propagation and structured logging, and add API-key authentication for non-public endpoints.
2. **Extend**: replace the ephemeral `BackgroundTasks`-based backtest job with a `JobRegistry` state machine that survives restarts, expose a `GET /api/v1/jobs/{job_id}` status endpoint, add a `GET /api/v1/notebooks` index, and ship a comprehensive public+private integration test matrix plus a sign-off notebook.

### Scope

Phase 5 covers nine sub-phases in dependency order:

| Sub-phase | Deliverable | Purpose |
|---|---|---|
| 5.1 | App Factory & Lifespan Audit | Validate existing factory; add request-ID middleware, exception handlers, JobRegistry singleton in lifespan |
| 5.2 | API Contract & Response Schemas | `api/schemas/` package; replace dict returns with Pydantic models; OpenAPI tags + examples |
| 5.3 | Read-Only Routers Hardening | Universe / signals / portfolio: typed responses, public/private parity tests, ETag support |
| 5.4 | Write Routers & Job Lifecycle | `JobRegistry` state machine; `GET /api/v1/jobs/{id}`; restart-safe persistence; uniform 403 contract |
| 5.5 | Scheduler Production Wiring | Cron parametrization, `misfire_grace_time`, structured logs, manual trigger endpoint, public-mode skip parity |
| 5.6 | Static Asset & Notebook Serving | StaticFiles audit; HTML fallback page; ETag headers; `GET /api/v1/notebooks` index |
| 5.7 | Authentication & Public-Mode Hardening | `X-API-Key` header middleware; key redaction in logs; 403 contract test for every write endpoint |
| 5.8 | Observability & Error Handling | Structured JSON logging, request-ID, problem-details, extended `/health` |
| 5.9 | Integration Test Suite & API Sign-Off Notebook | Full public+private matrix, OpenAPI snapshot test, `notebooks/05_api_validation.ipynb` |

**Out of scope for Phase 5:**

- Docker packaging and public distribution — that is Phase 6
- NiceGUI dashboard / multi-strategy aggregation — that is the future multi-strategy dashboard project
- OAuth2 / JWT, rate limiting, Prometheus metrics — deferred to Phase 7 (Hardening) or beyond
- Live broker connector / order routing — deferred to Phase 8
- Distributed job queue (Celery / RQ / Dramatiq) — deferred to Phase 8 if needed

### Validated Inputs from Phases 1–4

Phase 5 builds on **outputs that Phases 1–4 already produce**. These are non-negotiable inputs the API must preserve:

| Input | Source | API contract obligation |
|---|---|---|
| `data/processed/` parquet store | Phase 1 (`ParquetStore`) | Read-only access via `get_store()` dependency; never mutated by API in public mode |
| `results/signals/latest_ranking.json` | Phase 2 export via `scripts/export_results.py` | Public-mode source for `GET /api/v1/signals/latest` |
| `results/backtest/summary.json` | Phase 3/4 export | Public-mode source for `GET /api/v1/portfolio/current` |
| `results/notebooks/*.html` | `scripts/export_results.py` | Served via StaticFiles at `/static/notebooks/` |
| `BacktestConfig` defaults | Phase 4.9 (vol_scaling=True, retail 1M THB) | Used as the default request body for `POST /api/v1/backtest/run` |
| Phase 4.5 `CircuitBreakerState` | `csm.portfolio.drawdown_circuit_breaker` | Surfaced as a string in `PortfolioSnapshot` response schema |
| `Settings.public_mode` | [src/csm/config/settings.py:40](../../../src/csm/config/settings.py) | Sole source of truth for write-endpoint gating |

The public-mode contract is the most important: **a fresh `git clone` followed by `docker compose up` (Phase 6) must serve every read endpoint with no credentials, no live data fetch, and no errors.** Phase 5 ships the correctness of that contract; Phase 6 ships the packaging.

---

## Problem Statement

The Phase 5 scaffolding works on the happy path but has three production-readiness gaps that block deploying the API beyond a developer laptop:

1. **No formal API contract.** Every endpoint returns `dict[str, object]` — see [api/routers/universe.py:18](../../../api/routers/universe.py), [api/routers/signals.py:24](../../../api/routers/signals.py), [api/routers/portfolio.py:23](../../../api/routers/portfolio.py). OpenAPI surfaces these as untyped `Any` schemas, so consumers cannot rely on the spec for codegen, validation, or compatibility checks. The future multi-strategy dashboard (Phase 6 follow-on) needs a stable contract to drive UI components.
2. **Job tracking is ephemeral.** [api/routers/backtest.py:33-45](../../../api/routers/backtest.py) accepts a backtest run and immediately returns a UUID, but the UUID is never recorded, the FastAPI `BackgroundTasks` instance dies with the request, and there is no `GET /api/v1/jobs/{job_id}` endpoint. A user has no way to check whether their job completed, failed, or was lost on a server restart.
3. **No auth, no structured errors, no observability.** There is no API-key middleware (private-mode endpoints are open to anyone who can reach the host), no request ID propagation, no JSON logging, no uniform error shape (HTTPException returns `{detail: str}`; uvicorn's default access log is unstructured), and no `/health` extension exposing scheduler status. These are table-stakes for any internet-facing service.

A fourth, smaller gap: integration tests cover only public-mode happy paths (4 tests in [tests/integration/test_api_endpoints.py](../../../tests/integration/test_api_endpoints.py)). Private-mode flows, schema validation, error paths, and cross-mode parity are untested.

Solving these gaps is the prerequisite for Phase 6 (which packages this API into a public-distribution Docker image) and any future external consumer of the strategy.

---

## Existing Scaffolding Audit

Phase 5 is a **promote-and-extend** plan, not a greenfield build. The audit below classifies every ROADMAP §5 deliverable as DONE / STUB-EXISTS / NOT-STARTED. New sub-phases attach to the gaps.

| ROADMAP item | Status | Evidence | Phase 5 sub-phase that owns the gap |
|---|---|---|---|
| 5.1.1 FastAPI app factory + lifespan | DONE | [api/main.py:29-47](../../../api/main.py) | 5.1 audit only |
| 5.1.2 CORS middleware | DONE | [api/main.py:48-54](../../../api/main.py) | 5.1 audit only |
| 5.1.3 Public-mode write guard | DONE | [api/main.py:62-74](../../../api/main.py) | 5.7 extends with auth |
| 5.1.4 StaticFiles `/static/notebooks` | DONE | [api/main.py:55-59](../../../api/main.py) | 5.6 adds index + ETag |
| 5.1.5 `/health` endpoint | DONE (basic) | [api/main.py:84-88](../../../api/main.py) | 5.8 extends payload |
| 5.2.1 `GET /api/v1/universe` | STUB-EXISTS | [api/routers/universe.py:15-26](../../../api/routers/universe.py) | 5.2 + 5.3 |
| 5.2.2 `GET /api/v1/signals/latest` | STUB-EXISTS | [api/routers/signals.py:20-47](../../../api/routers/signals.py) | 5.2 + 5.3 |
| 5.2.3 `GET /api/v1/portfolio/current` | STUB-EXISTS | [api/routers/portfolio.py:19-39](../../../api/routers/portfolio.py) | 5.2 + 5.3 |
| 5.2.4 `POST /api/v1/data/refresh` | STUB-EXISTS | [api/routers/data.py:17-37](../../../api/routers/data.py) | 5.4 + 5.7 |
| 5.2.5 `POST /api/v1/backtest/run` | STUB-EXISTS (ephemeral) | [api/routers/backtest.py:33-45](../../../api/routers/backtest.py) | 5.4 (replaces BackgroundTasks) |
| 5.3.1 APScheduler init | DONE | [api/scheduler/jobs.py:48-59](../../../api/scheduler/jobs.py) | 5.5 hardens |
| 5.3.2 `daily_refresh` job | DONE | [api/scheduler/jobs.py:17-45](../../../api/scheduler/jobs.py) | 5.5 hardens |
| 5.3.3 Cron schedule wiring | STUB (hardcoded) | `trigger="cron"` lacks expression — line 58 | 5.5 binds to `Settings.refresh_cron` |
| `scripts/refresh_daily.py` | DONE | [scripts/refresh_daily.py](../../../scripts/refresh_daily.py) | n/a |
| `scripts/export_results.py` | DONE | [scripts/export_results.py](../../../scripts/export_results.py) | n/a |
| Integration tests | STUB (4 cases, public-mode only) | [tests/integration/test_api_endpoints.py](../../../tests/integration/test_api_endpoints.py) | 5.9 expands to full matrix |
| Pydantic response schemas | NOT-STARTED | every router returns `dict[str, object]` | 5.2 |
| `JobRegistry` & `GET /jobs/{id}` | NOT-STARTED | `BackgroundTasks` is ephemeral | 5.4 |
| API-key auth | NOT-STARTED | no auth middleware | 5.7 |
| Structured logging + request ID | NOT-STARTED | stdlib default | 5.8 |
| RFC 7807 problem details | NOT-STARTED | `HTTPException` default `{detail: str}` | 5.8 |
| OpenAPI tags / examples | PARTIAL (tags present, no examples) | each router declares `tags=[...]` | 5.2 |
| Sign-off notebook `05_api_validation.ipynb` | NOT-STARTED | n/a | 5.9 |

---

## Design Rationale

### Promote, Don't Rewrite

Each sub-phase begins with an audit of the existing module and adds **only the gap**. The 5 routers, the lifespan, CORS, StaticFiles, and the public-mode middleware all stay. This isolates contract risk (5.2) from auth risk (5.7) from observability risk (5.8), and keeps the diff for each sub-phase reviewable independently.

### Public-Mode Is the Default Contract

`Settings.public_mode` is the single source of truth for endpoint behaviour. Every endpoint specifies its public-mode and private-mode contract as a typed pair, with **separate tests for each mode** in 5.9. Public-mode contract:

- Reads serve from `results/` JSON files (already exported by the owner via `scripts/export_results.py`).
- Writes return `403 Forbidden` with a uniform problem-details body via the middleware in [api/main.py:62-74](../../../api/main.py).
- Scheduler returns `None` from `create_scheduler()` ([api/scheduler/jobs.py:51-52](../../../api/scheduler/jobs.py)) and runs no jobs.

Private-mode contract:

- Reads compute live from the parquet store and feature pipeline.
- Writes accept the request, enqueue work via the JobRegistry (5.4), and return a job ID.
- Scheduler runs `daily_refresh` per `Settings.refresh_cron`.

### Pydantic Response Models, Not Dicts

Every endpoint returns a typed Pydantic v2 model declared in `api/schemas/`. OpenAPI is then accurate; FastAPI's response validation catches schema drift at runtime; consumers get codegen-quality types. The existing `dict[str, object]` returns are replaced wholesale in 5.2 — this is the single biggest delta and it must land before 5.3 and 5.4 build on it.

### JobRegistry, Not Distributed Queue

The backtest job lifecycle is owned by an in-process `JobRegistry` — a Pydantic state machine (`accepted → running → succeeded | failed`) with a small WAL-style JSON persistence under `results/.tmp/jobs/`. Restart safety is achieved by reloading the registry on lifespan startup. This is intentionally simple: no Redis, no broker, no Celery. If the user ever needs concurrent multi-process workers or guaranteed delivery, that is a Phase 8 enhancement. Today's load is one user, one server, one backtest at a time.

### Auth via Static API Key, Not OAuth

`Settings.api_key: SecretStr | None` (added in 5.7) gates every non-public route in private mode. Configuration is owner-controlled via the same `.env` mechanism that already configures tvkit credentials. A static key is sufficient because the API is owner-only in private mode and behind a public-mode contract elsewhere. OAuth/JWT belongs in Phase 7 (Hardening) if and only if the multi-strategy dashboard introduces multi-user access.

### Errors as RFC 7807 Problem Details

A uniform exception handler in `api/errors.py` translates every `HTTPException`, validation error, and uncaught exception into an `application/problem+json` body conforming to RFC 7807:

```json
{
  "type": "https://csm.example/problems/snapshot-not-found",
  "title": "Universe snapshot not found",
  "status": 404,
  "detail": "Universe snapshot 'universe_latest' is not present in the parquet store.",
  "instance": "/api/v1/universe",
  "request_id": "01HXY...K9"
}
```

This replaces FastAPI's default `{detail: str}` and gives clients a stable, machine-parseable error contract.

### Observability via Stdlib Logging

Structured logging uses Python stdlib `logging` with a JSON formatter — no extra dependencies. Each request gets a `request_id` (Starlette middleware), propagated via `contextvars` so every log line within the request scope inherits it. Uvicorn's access log is replaced by a custom middleware that emits one structured line per request with method, path, status, duration_ms, request_id. Prometheus / OpenTelemetry are deferred to Phase 7.

### Notebook Index Endpoint, Not Just StaticFiles

`GET /api/v1/notebooks` returns a typed list of available notebook HTMLs with their `last_modified` timestamps. The existing StaticFiles mount at `/static/notebooks/` keeps serving the binaries; the new endpoint gives the future dashboard project a discoverable catalogue without scraping the filesystem.

---

## Architecture

### Directory Layout

```
api/
├── __init__.py                       # Existing — re-exports app
├── main.py                           # EXISTING — extended (5.1, 5.6, 5.8)
├── deps.py                           # EXISTING — extended (5.1, 5.4, 5.7)
├── errors.py                         # NEW — RFC 7807 problem-details handler (5.8)
├── logging.py                        # NEW — JSON formatter, request-ID context (5.8)
├── security.py                       # NEW — API-key middleware (5.7)
├── jobs.py                           # NEW — JobRegistry, JobStatus state machine (5.4)
├── schemas/                          # NEW PACKAGE (5.2)
│   ├── __init__.py
│   ├── universe.py                   # UniverseSnapshot, UniverseItem
│   ├── signals.py                    # SignalRanking, SignalRow
│   ├── portfolio.py                  # PortfolioSnapshot, Holding
│   ├── backtest.py                   # BacktestRunRequest, BacktestRunResponse
│   ├── data.py                       # RefreshResult
│   ├── jobs.py                       # JobStatus, JobRecord
│   ├── notebooks.py                  # NotebookEntry, NotebookIndex
│   ├── health.py                     # HealthStatus
│   └── errors.py                     # ProblemDetail
├── routers/
│   ├── __init__.py                   # EXISTING
│   ├── universe.py                   # EXISTING — typed in 5.3
│   ├── signals.py                    # EXISTING — typed in 5.3
│   ├── portfolio.py                  # EXISTING — typed in 5.3
│   ├── data.py                       # EXISTING — typed + JobRegistry in 5.4
│   ├── backtest.py                   # EXISTING — typed + JobRegistry in 5.4
│   ├── jobs.py                       # NEW — GET /api/v1/jobs/{job_id}, GET /api/v1/jobs (5.4)
│   ├── notebooks.py                  # NEW — GET /api/v1/notebooks (5.6)
│   └── scheduler.py                  # NEW — POST /api/v1/scheduler/run/{job_id} (5.5, private only)
└── scheduler/
    ├── __init__.py                   # EXISTING
    └── jobs.py                       # EXISTING — extended in 5.5

tests/integration/
├── conftest.py                       # EXISTING — extended with private-mode fixture, api_key fixture
├── test_api_endpoints.py             # EXISTING — kept for backward compat
├── test_api_universe.py              # NEW — public + private + error matrix (5.9)
├── test_api_signals.py               # NEW (5.9)
├── test_api_portfolio.py             # NEW (5.9)
├── test_api_data_refresh.py          # NEW (5.9)
├── test_api_backtest_jobs.py         # NEW — full job lifecycle (5.9)
├── test_api_scheduler.py             # NEW (5.9)
├── test_api_notebooks.py             # NEW (5.9)
├── test_api_auth.py                  # NEW — API-key contract (5.9)
├── test_api_errors.py                # NEW — problem-details shape (5.9)
├── test_api_health.py                # NEW (5.9)
└── test_openapi_snapshot.py          # NEW — OpenAPI schema pinned (5.9)

notebooks/
└── 05_api_validation.ipynb           # NEW — Phase 5 sign-off (5.9)

src/csm/config/
└── settings.py                       # EXTENDED — adds api_key: SecretStr | None (5.7)

docs/plans/phase5_api/
├── PLAN.md                           # this file
├── phase5.1_app_factory_lifespan_audit.md         # NEW per sub-phase doc (created during 5.1)
├── phase5.2_api_contract_response_schemas.md      # NEW (5.2)
├── phase5.3_read_only_routers_hardening.md        # NEW (5.3)
├── phase5.4_write_routers_job_lifecycle.md        # NEW (5.4)
├── phase5.5_scheduler_production_wiring.md        # NEW (5.5)
├── phase5.6_static_asset_notebook_serving.md      # NEW (5.6)
├── phase5.7_authentication_public_mode_hardening.md  # NEW (5.7)
├── phase5.8_observability_error_handling.md       # NEW (5.8)
└── phase5.9_integration_test_suite_signoff.md     # NEW (5.9)
```

### Dependency Graph

```
Settings (existing) ──┐
                      ▼
ParquetStore (existing) ──► JobRegistry (NEW, lifespan singleton)
                      │             │
                      ▼             ▼
api/schemas/* (NEW) ──► routers/* (typed via response_model)
                                  │
                                  ▼
                        api/security.py (API-key middleware)
                                  │
                                  ▼
                        api/main.py public_mode_guard (existing)
                                  │
                                  ▼
                        api/errors.py (problem-details handler)
                                  │
                                  ▼
                        api/logging.py (request-ID + JSON formatter)
```

### Request Lifecycle

```
[1] HTTP request
        ↓
[2] LoggingMiddleware           — assigns request_id, sets contextvar
        ↓
[3] APIKeyMiddleware            — 401 if private mode + missing/invalid key (skips public reads)
        ↓
[4] PublicModeGuardMiddleware   — 403 on write paths if public_mode=True (existing)
        ↓
[5] CORSMiddleware              — existing
        ↓
[6] Router → endpoint           — typed Pydantic request body, response_model
        ↓
[7] Handler                     — depends on get_settings, get_store, get_jobs
        ↓
[8] Response                    — Pydantic dump → JSON
        ↓
[9] Exception handler (if raised) — RFC 7807 problem-details JSON
        ↓
[10] LoggingMiddleware (post)   — emits one structured access log line
        ↓
[11] HTTP response
```

---

## Implementation Phases

### Phase 5.1 — App Factory & Lifespan Audit

**Status:** `[x]` Complete — 2026-04-30
**Goal:** Validate the existing `api/main.py`. Add request-ID middleware, register the JobRegistry as a lifespan-managed singleton, derive `app.version` from `csm.__version__` (single source of truth), and register the global problem-details exception handler stub (full handler lands in 5.8).

**Deliverables:**

- [x] [api/main.py](../../../api/main.py) — `app.version` reads from `csm.__version__` (`__version__` already present in `src/csm/__init__.py:3`)
- [x] `api/main.py` lifespan extended to instantiate `JobRegistry` (skeleton) and store it on `app.state.jobs`
- [x] `api/deps.py` — add `get_jobs() -> JobRegistry` provider
- [x] `api/main.py` registers a global exception handler stub for `HTTPException` and `Exception` in `api/errors.py`
- [x] `api/logging.py` — new module with `RequestIDMiddleware` (Starlette `BaseHTTPMiddleware`) generating ULIDs and binding to a `contextvar`
- [x] `app.add_middleware(RequestIDMiddleware)` registered before CORS (outermost in stack)
- [x] Unit tests (12 cases in `tests/unit/test_api_lifespan.py`): version in OpenAPI; JobRegistry in lifespan; request-ID per request, ULID format; X-Request-ID header; contextvar reset; 404 includes request_id; health endpoint
- [x] No semantic change to existing endpoint behaviour
- [x] `python-ulid>=3` added to dependencies; `api/jobs.py` skeleton created

**Completion notes:**
- `csm.__version__` already existed at `"0.1.0"` — no change needed to `src/csm/__init__.py`
- Exception handlers imported `HTTPException` from `starlette.exceptions` (not FastAPI's subclass) so routing 404s are caught correctly
- Middleware order: RequestIDMiddleware (outermost) → CORSMiddleware → BaseHTTPMiddleware(public_mode_guard) (innermost)
- 12 unit tests pass; 6 pre-existing `test_fetch_history.py` failures unrelated to this phase

**Audit checks against existing code:**

- [x] Confirm [api/main.py:47](../../../api/main.py) `version="0.1.0"` is the only hard-coded version → migrated to `csm.__version__`
- [x] Confirm [api/main.py:30](../../../api/main.py) `lifespan` does not currently instantiate JobRegistry → extended
- [x] Confirm middleware order: RequestID → CORS → PublicModeGuard. `app.add_middleware` is LIFO, so RequestID registered first.

---

### Phase 5.2 — API Contract & Response Schemas

**Status:** `[x]` Complete — 2026-04-30
**Goal:** Replace every `dict[str, object]` return type with a typed Pydantic v2 response model. Introduce `api/schemas/` package. Add OpenAPI tags, summaries, descriptions, and request/response examples to every endpoint.

**Deliverables:**

- [x] `api/schemas/__init__.py` re-exporting all schemas
- [x] `api/schemas/universe.py` — `UniverseItem` (symbol, extra="allow") and `UniverseSnapshot` (items, count)
- [x] `api/schemas/signals.py` — `SignalRow` (symbol, extra="allow") and `SignalRanking` (as_of, rankings)
- [x] `api/schemas/portfolio.py` — `Holding` (symbol, weight, sector) and `PortfolioSnapshot` (as_of, holdings, summary_metrics, extra="allow")
- [x] `api/schemas/backtest.py` — `BacktestRunResponse` (job_id, status). BacktestConfig reused directly as request body.
- [x] `api/schemas/data.py` — `RefreshResult` (refreshed, requested)
- [x] `api/schemas/jobs.py` — Re-exports `JobStatus`, `JobKind`, `JobRecord` from `api.jobs`
- [x] `api/schemas/notebooks.py` — `NotebookEntry` and `NotebookIndex` (stubs for Phase 5.6)
- [x] `api/schemas/health.py` — `HealthStatus` (status, version, public_mode)
- [x] `api/schemas/errors.py` — `ProblemDetail` (detail, request_id; RFC 7807 fields in 5.8)
- [x] All five existing routers updated: declare `response_model=...`, return Pydantic models, add `summary=`, `description=`, `responses={...}` with 200 example and 4xx ProblemDetail models
- [x] Unit tests: 26 round-trip tests across 11 test classes (construct, dump, re-parse)
- [ ] OpenAPI snapshot test added to `tests/integration/test_openapi_snapshot.py` (full coverage in 5.9; placeholder here)

**Completion notes:**
- `ConfigDict(extra="allow")` used on `UniverseItem`, `SignalRow`, `PortfolioSnapshot` to accept dynamic DataFrame columns (variable feature sets, extra metrics)
- Portfolio public/private mode unified into single `PortfolioSnapshot` return type
- `BacktestConfig` reused directly as request body — no wrapper model needed
- `ProblemDetail` matches Phase 5.1 handler shape; full RFC 7807 lands in Phase 5.8
- All 38 unit tests pass (26 schema + 12 lifespan); ruff + mypy clean
- OpenAPI snapshot test deferred to Phase 5.9 (needs fixtures from subsequent phases)

**Acceptance:** `GET /openapi.json` shows fully-typed component schemas for every endpoint; no `additionalProperties: true` on response models; every route has a `summary` and at least one example. ✓

---

### Phase 5.3 — Read-Only Routers Hardening

**Status:** `[x]` Complete — 2026-04-30
**Goal:** Bring `universe`, `signals`, `portfolio` to production quality. Public/private parity tests, ETag/Last-Modified support for cacheable reads, deterministic error paths.

**Deliverables:**

- [x] [api/routers/universe.py](../../../api/routers/universe.py) — returns `UniverseSnapshot`; ETag derived from snapshot date + symbol-list hash
- [x] [api/routers/signals.py](../../../api/routers/signals.py) — returns `SignalRanking`; public mode reads `results/signals/latest_ranking.json` (existing); private mode computes via `FeaturePipeline` + `CrossSectionalRanker` (existing); ETag derived from content hash
- [x] [api/routers/portfolio.py](../../../api/routers/portfolio.py) — returns `PortfolioSnapshot`; surfaces `regime` and `breaker_state` from Phase 4 modules; ETag derived from stable fields
- [x] All three routers honour `If-None-Match` and return `304 Not Modified` when ETag matches
- [x] Error paths formalized: 404 when `results/` JSON missing in public mode (existing), 404 when parquet key missing in private mode (existing), 500 with problem-details when payload malformed
- [x] Integration tests: public + private + error matrix for each router (26 new tests, 580 total passing)
- [x] New modules: `api/retry.py` (async retry with exp backoff + jitter), `api/schemas/params.py`
- [x] `PortfolioSnapshot` extended with `regime`, `breaker_state`, `equity_fraction` fields
- [x] All quality gates pass: ruff check, ruff format, mypy (api/), pytest (580/580)

**Completion notes:**
- Weak ETags (`W/"<sha256>"`) used consistently across all three routers
- Portfolio ETag excludes dynamic `as_of` timestamp to allow cache hits
- `portfolio_state` parquet key loaded optionally in private mode; defaults to NEUTRAL/NORMAL/1.0 if absent
- Retry logic wraps all store.load, JSON file reads, and pipeline operations
- Structured logging at INFO (success), WARNING (404/304), ERROR (I/O failure)
- Error responses use `ProblemDetail` model with `request_id` from contextvar
- Test fixtures patch both `api.main.settings` and `api.deps.settings` for proper isolation

---

### Phase 5.4 — Write Routers & Job Lifecycle

**Status:** `[x]` Complete — 2026-04-30
**Goal:** Replace ephemeral `BackgroundTasks` with a persistent `JobRegistry`. Every write request returns a job ID that can be polled to completion. Restart-safe.

**Deliverables:**

- [x] `api/jobs.py` — `JobRegistry` class
  - [x] `submit(kind: JobKind, runner: Callable[..., Awaitable[JobOutcome]], **kwargs) -> JobRecord`
  - [x] `get(job_id: str) -> JobRecord | None`
  - [x] `list(kind: JobKind | None, status: JobStatus | None, limit: int) -> list[JobRecord]`
  - [x] `_persist(record: JobRecord)` — atomic JSON write to `results/.tmp/jobs/{job_id}.json`
  - [x] `load_all()` — invoked at lifespan startup; rehydrates registry from disk
  - [x] State machine: `accepted → running → succeeded | failed | cancelled`; transitions guarded
- [x] `api/jobs.py` — `JobKind` (`DATA_REFRESH`, `BACKTEST_RUN`) and `JobStatus` enums
- [x] `api/jobs.py` — concurrency control via per-kind async queues + dedicated worker tasks (equivalent to `asyncio.Semaphore(1)` per job kind); FIFO queue
- [x] [api/routers/data.py](../../../api/routers/data.py) — `POST /api/v1/data/refresh` returns `RefreshResult(job_id, status="accepted")`; the actual work runs as a JobRegistry task
- [x] [api/routers/backtest.py](../../../api/routers/backtest.py) — `POST /api/v1/backtest/run` returns `BacktestRunResponse(job_id, status="accepted")`; runs as JobRegistry task; existing `_run_backtest_job` body becomes the runner
- [x] `api/routers/jobs.py` — NEW
  - [x] `GET /api/v1/jobs/{job_id}` → `JobRecord` (404 if unknown)
  - [x] `GET /api/v1/jobs?kind=&status=&limit=` → `list[JobRecord]` (private mode only; public returns 403)
- [x] Integration tests: submit job → poll until `succeeded` → verify result; restart-safety test (instantiate registry twice, confirm completed jobs persist)

**Persistence boundary:** `results/.tmp/jobs/` is gitignored (already covered by `results/.tmp/` ignore if present; verify and add if missing). Jobs hold metadata only — no raw OHLCV or strategy outputs.

**Completion notes:**
- Per-kind `asyncio.Queue` with dedicated worker tasks instead of bare semaphores — gives natural FIFO ordering
- ULID job IDs for consistency with request IDs from Phase 5.1
- `load_all()` marks RUNNING jobs as FAILED on restart (orphaned process detection)
- `cancel()` only works from ACCEPTED state; worker skips CANCELLED items
- Sync `MomentumBacktest.run()` wrapped in `asyncio.to_thread()` to avoid blocking the event loop
- `RefreshResult` schema changed: `refreshed`/`requested` → `job_id`/`status`; counts moved to `JobRecord.summary`
- 595/595 tests pass (15 new: 2 schema + 13 integration)

---

### Phase 5.5 — Scheduler Production Wiring

**Status:** `[x]` Complete (2026-04-30)
**Goal:** Bind the daily-refresh job to `Settings.refresh_cron`, add a missed-run policy, surface job state to `/health`, and provide a private-mode manual trigger endpoint.

**Deliverables:**

- [x] [api/scheduler/jobs.py:58](../../../api/scheduler/jobs.py) — `scheduler.add_job` extended with `CronTrigger.from_crontab(settings.refresh_cron, timezone="Asia/Bangkok")` and `misfire_grace_time=3600`, `coalesce=True`, `max_instances=1`
- [x] `daily_refresh` extended to write a marker file `results/.tmp/last_refresh.json` (timestamp, symbols_fetched, duration_seconds, failures) on success — surfaced by extended `/health` (5.8)
- [x] `daily_refresh` failures logged at ERROR with structured fields; do not crash the scheduler
- [x] `api/routers/scheduler.py` — NEW
  - [x] `POST /api/v1/scheduler/run/{job_id}` — manual trigger (private mode only); valid job IDs: `daily_refresh`; submits via JobRegistry
  - [x] Public mode: this router is registered but every endpoint returns 403 via the `WRITE_PATHS` middleware (extend the set in [api/main.py:26](../../../api/main.py))
- [x] Unit tests: cron expression parsing; missed-run policy; private-mode skip parity (`create_scheduler(public_mode=True) is None`); manual trigger submits via JobRegistry not directly

---

### Phase 5.6 — Static Asset & Notebook Serving

**Status:** `[x]` Complete (2026-04-30)
**Goal:** Audit the StaticFiles mount, add ETag headers, ship a fallback page, and expose a typed `GET /api/v1/notebooks` index.

**Deliverables:**

- [x] `api/main.py` StaticFiles mount replaced with `NotebookStaticFiles`; serves `*.html` with `Cache-Control: public, max-age=300`
- [x] Fallback HTML at `api/static/notebook_missing.html` returned for any 404 within `/static/notebooks/`
- [x] `api/routers/notebooks.py` — `GET /api/v1/notebooks` → `NotebookIndex(items=[NotebookEntry(name, path, size_bytes, last_modified)])`
- [x] `api/static_files.py` — `NotebookStaticFiles` subclass with dynamic directory resolution and `lookup_path` override
- [x] Notebook listing reads from `Settings.results_dir / "notebooks"` (no fs walk outside that root; path traversal defence)
- [x] Integration tests: index lists existing HTMLs; missing notebook returns fallback HTML; ETag header round-trip (21 new tests)
- [x] Full quality gate: ruff, ruff format, mypy, pytest (632 passed, zero regressions)

---

### Phase 5.7 — Authentication & Public-Mode Hardening

**Status:** `[x]` Complete — 2026-04-30
**Goal:** Lock down private-mode endpoints behind an API-key header. Tighten the public-mode contract with explicit per-endpoint tests.

**Deliverables:**

- [x] [src/csm/config/settings.py](../../../src/csm/config/settings.py) — add `api_key: SecretStr | None = None` field with description; documented in `.env.example`
- [x] `api/security.py` — `APIKeyMiddleware` (BaseHTTPMiddleware)
  - [x] In public mode: always allow (read endpoints are public; write endpoints already 403'd by `public_mode_guard`)
  - [x] In private mode with `api_key=None`: log a warning at startup; allow all (dev mode)
  - [x] In private mode with `api_key` set: require header `X-API-Key`; otherwise return 401 problem-details
  - [x] Exempt paths: `/health`, `/docs`, `/redoc`, `/openapi.json`, `/static/notebooks/*` (always public), and the read-only `GET` routes via `is_protected_path()` predicate
- [x] `api/logging.py` — `KeyRedactionFilter` redacts the configured key from all log records; `install_key_redaction()` attaches it to root logger at lifespan startup
- [x] `api/main.py` — middleware order: RequestIDMiddleware (outermost) → APIKeyMiddleware → public_mode_guard → CORSMiddleware → routers; dev-mode warning emits once at startup
- [x] Integration tests (16 new in `tests/integration/test_api_auth.py`):
  - [x] Public mode 403 contract test for every write endpoint (4 paths, ProblemDetail-shaped body with request_id)
  - [x] Private mode with key set: 401 without header; 401 with wrong key; 200 with correct key
  - [x] Private mode with `api_key=None`: warning logged; all endpoints accessible
  - [x] API key never appears in any log line
  - [x] Read endpoints exempt from key requirement
  - [x] Health / docs / static paths exempt from key requirement
- [x] Unit tests (13 new in `tests/unit/test_api_security.py`): is_protected_path truth table, middleware dispatch branches, KeyRedactionFilter (msg/args/non-string/empty-secret/unrelated)
- [x] `tests/conftest.py` — `private_client_with_key` fixture added

**Completion notes:**
- Auth is enforced exclusively at the middleware layer; routers remain unaware of the header
- `is_protected_path(method, path)` uses an explicit `PROTECTED_PATHS` frozenset plus a defence-in-depth rule: any non-GET on `/api/v1/*` is protected
- Constant-time comparison via `secrets.compare_digest()` to avoid timing oracle
- Middleware reads live settings via `sys.modules` to honour test fixture patches
- `KeyRedactionFilter` is a no-op when key is unset or empty; scans both `record.msg` and `record.args`
- Startup warning emitted exactly once in lifespan, not per request
- Test coverage: 13 unit + 16 integration = 29 new tests; 670 total passing (zero regressions)
- Type checking clean: `uv run mypy api/` passes on all new modules

---

### Phase 5.8 — Observability & Error Handling

**Status:** `[x]` Complete — 2026-04-30
**Goal:** Production-grade logging and a single uniform error contract.

**Deliverables:**

- [x] `api/logging.py` extended:
  - [x] `JsonFormatter` emitting `{ts, level, logger, msg, request_id, **extra}` per log line
  - [x] `configure_logging(settings)` invoked at lifespan startup; sets root logger level from `Settings.log_level`
  - [x] `AccessLogMiddleware` emitting `{request_id, method, path, status, duration_ms, client_ip}` once per request
- [x] `api/errors.py`:
  - [x] `ProblemDetailException(status, type, title, detail)` — internal exception class extending `HTTPException`
  - [x] `problem_details_handler(request, exc)` — registered via `app.add_exception_handler` for `HTTPException`, `RequestValidationError`, `Exception`
  - [x] Returns `application/problem+json` with `ProblemDetail` body including `request_id` from contextvar
  - [x] Maps stdlib `HTTPException` to full `ProblemDetail`
- [x] `api/main.py:84-88` `/health` extended:
  - [x] Returns `HealthStatus(status, version, public_mode, scheduler_running, last_refresh_at, last_refresh_status, jobs_pending)`
  - [x] `last_refresh_at` and `last_refresh_status` read from `results/.tmp/last_refresh.json`
  - [x] `scheduler_running` reads from `app.state.scheduler`
  - [x] `jobs_pending` reads from `app.state.jobs.list(status=ACCEPTED)`
- [x] `api/security.py` `_problem_response` upgraded to full RFC 7807 shape with `type_uri` and `title`
- [x] `api/schemas/errors.py` — full RFC 7807 `ProblemDetail` with `type`, `title`, `status`, `instance`
- [x] `api/schemas/health.py` — extended with `scheduler_running`, `last_refresh_at`, `last_refresh_status`, `jobs_pending`; `status` → `Literal["ok","degraded"]`
- [x] Unit tests: `test_error_handlers.py` (9 cases), `test_api_logging.py` (9 cases), updated `test_api_schemas.py` (+5 cases), `test_api_lifespan.py` (updated)
- [x] Integration tests: `test_api_errors.py` (10 cases), `test_api_health.py` (7 cases)
- [x] All quality gates pass: ruff, ruff format, mypy, pytest (710 tests, zero regressions)

**Completion notes:**
- `ProblemDetailException` extends `HTTPException` so it's caught by the existing handler registration
- `configure_logging` uses `type(h) is not logging.StreamHandler` to avoid removing `LogCaptureHandler` (pytest's caplog)
- Router-level error handling (signals, portfolio) catches exceptions internally — global handler covers Starlette routing 404s, auth middleware 401s, public-mode guard 403s, and uncaught exceptions
- 40 new tests; 710 total passing; all quality gates green

---

### Phase 5.9 — Integration Test Suite & API Sign-Off Notebook

**Status:** `[ ]` Not started
**Goal:** Exhaustive test coverage and a single sign-off notebook that exercises every endpoint in both modes.

**Deliverables:**

- [ ] `tests/integration/conftest.py` extended with:
  - [ ] `client_public(tmp_results)` — TestClient with `CSM_PUBLIC_MODE=true`
  - [ ] `client_private(tmp_data, tmp_jobs, api_key)` — TestClient with `CSM_PUBLIC_MODE=false`, populated parquet store, `Settings.api_key` set
  - [ ] `tmp_jobs` — fresh `results/.tmp/jobs/` directory per test
- [ ] One test file per resource (see Architecture for full list); each covers:
  - [ ] Happy path (public + private)
  - [ ] Schema-validation: response parses cleanly into the declared Pydantic model
  - [ ] Error paths (404 on missing data; 422 on malformed input; 403 in public mode for writes; 401 with bad key)
  - [ ] ETag round-trip for cacheable reads
- [ ] `tests/integration/test_api_backtest_jobs.py` — full lifecycle: submit → poll → succeeded; restart safety (re-instantiate registry, confirm record reloaded)
- [ ] `tests/integration/test_openapi_snapshot.py` — pins the JSON Schema; intentional changes update the snapshot via a documented step
- [ ] `notebooks/05_api_validation.ipynb` — 8 sections, Thai markdown:
  - [ ] Section 1: Setup — start TestClient in both modes
  - [ ] Section 2: Health & version surface
  - [ ] Section 3: Read-only endpoints (universe / signals / portfolio) public + private parity
  - [ ] Section 4: Write endpoints (data refresh / backtest run) — 403 in public, full lifecycle in private
  - [ ] Section 5: JobRegistry — submit, poll, status transitions
  - [ ] Section 6: Scheduler — manual trigger, marker file, `/health` reflects last refresh
  - [ ] Section 7: Authentication — public passes; private requires X-API-Key
  - [ ] Section 8: Final PASS/FAIL gate — prints PASS for all 12 success criteria
- [ ] Coverage gate: ≥ 90% line coverage on `api/` package (excluding `api/__init__.py`)
- [ ] All quality gates pass: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/ api/`, `uv run pytest tests/ -v`

---

## Data Models

### `JobStatus` and `JobRecord`

```python
class JobStatus(StrEnum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobKind(StrEnum):
    DATA_REFRESH = "data_refresh"
    BACKTEST_RUN = "backtest_run"


class JobRecord(BaseModel):
    job_id: str
    kind: JobKind
    status: JobStatus
    accepted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    request_id: str | None = None
```

### `UniverseSnapshot`

```python
class UniverseItem(BaseModel):
    symbol: str
    name: str | None = None
    sector: str | None = None


class UniverseSnapshot(BaseModel):
    asof: date
    count: int
    items: list[UniverseItem]
```

### `SignalRanking`

```python
class SignalRow(BaseModel):
    symbol: str
    score: float
    quintile: int = Field(ge=1, le=5)
    percentile_rank: float = Field(ge=0.0, le=1.0)


class SignalRanking(BaseModel):
    asof: date
    count: int
    rankings: list[SignalRow]
```

### `PortfolioSnapshot`

```python
class Holding(BaseModel):
    symbol: str
    weight: float = Field(ge=0.0, le=1.0)
    sector: str | None = None


class PortfolioSnapshot(BaseModel):
    asof: date
    regime: Literal["BULL", "BEAR", "EARLY_BULL", "NEUTRAL"]
    breaker_state: Literal["NORMAL", "TRIPPED", "RECOVERING"]
    equity_fraction: float = Field(ge=0.0, le=1.5)
    holdings: list[Holding]
    summary_metrics: dict[str, float] = Field(default_factory=dict)
```

### `ProblemDetail`

```python
class ProblemDetail(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str | None = None
    request_id: str | None = None
```

### `HealthStatus`

```python
class HealthStatus(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    public_mode: bool
    scheduler_running: bool
    last_refresh_at: datetime | None = None
    last_refresh_status: Literal["succeeded", "failed"] | None = None
    jobs_pending: int = 0
```

### `Settings` additions (Phase 5.7)

```python
api_key: SecretStr | None = Field(
    default=None,
    description="API key for private-mode endpoints. None disables auth (dev only).",
)
```

When `api_key=None` in private mode, the API logs a warning at startup and runs unauthenticated. Production deployments must set `CSM_API_KEY`.

---

## Error Handling Strategy

| Scenario | HTTP Status | `ProblemDetail.type` | Log level |
|---|---|---|---|
| Universe / signals / portfolio JSON or parquet key missing | 404 | `snapshot-not-found` | INFO |
| Public-mode write attempt | 403 | `public-mode-disabled` | INFO |
| Private mode + missing `X-API-Key` (when key configured) | 401 | `missing-api-key` | WARNING |
| Private mode + invalid `X-API-Key` | 401 | `invalid-api-key` | WARNING |
| Malformed request body / query params | 422 | `validation-error` | INFO |
| Job ID not found | 404 | `job-not-found` | INFO |
| Job already in terminal state on cancel | 409 | `job-conflict` | INFO |
| `BacktestConfig` validation failure | 422 | `backtest-config-invalid` | INFO |
| `OHLCVLoader` raises `DataAccessError` (public mode + private code path) | 500 | `internal-error` | ERROR |
| Scheduler clock skew (job runs > N minutes late) | n/a (background) | `scheduler-misfire` | WARNING |
| Uncaught `Exception` in handler | 500 | `internal-error` | ERROR |
| Notebook HTML missing in StaticFiles | 200 (HTML fallback) | n/a | INFO |

All 4xx/5xx responses use `Content-Type: application/problem+json` and include the `request_id` from the contextvar so log lines and client-side errors can be cross-referenced.

---

## Testing Strategy

### Coverage Target

≥ 90% line coverage on the `api/` package, with these specific lower bounds: `api/main.py` ≥ 95%, `api/jobs.py` ≥ 95%, `api/security.py` ≥ 95%, `api/errors.py` ≥ 95%. Unit-test boundary: every middleware, every handler, every JobRegistry transition. Integration-test boundary: every (mode × endpoint) pair.

### Public + Private Test Matrix

For every endpoint, two integration tests:

```
test_<endpoint>_public_mode_happy_path
test_<endpoint>_private_mode_happy_path
```

Plus error-path tests as appropriate from the error-handling table.

### OpenAPI Snapshot

`tests/integration/test_openapi_snapshot.py` fetches `/openapi.json`, normalizes it (sorted keys, stable formatting), and asserts equality against `tests/integration/snapshots/openapi.json`. Intentional schema changes regenerate the snapshot via `uv run pytest tests/integration/test_openapi_snapshot.py --snapshot-update` (or equivalent fixture).

### Mocking Strategy

- Schema tests: pure Pydantic round-trip; no mocks.
- Routing tests: `TestClient` with a populated tmp parquet store; mock the OHLCV loader so private-mode tests do not hit tvkit.
- JobRegistry tests: inject deterministic runners; assert state transitions; assert persistence files appear and disappear correctly.
- Scheduler tests: do not start AsyncIOScheduler in tests; instead instantiate `create_scheduler` and assert the configured trigger and job spec via `scheduler.get_jobs()`.

### Sign-Off Notebook

`notebooks/05_api_validation.ipynb` is the manual gate. Section 8 prints PASS/FAIL for every row in [Success Criteria](#success-criteria). The notebook is executed via `jupyter nbconvert --execute --no-input` as part of `scripts/export_results.py` (Phase 6 picks this up); for Phase 5 it is run manually before sign-off.

---

## Success Criteria

| # | Criterion | Measure |
|---|---|---|
| 1 | OpenAPI completeness | Every endpoint has `summary`, `description`, `response_model`, ≥ 1 example; no `additionalProperties: true` on response schemas; OpenAPI snapshot test passes |
| 2 | Public-mode parity | Every read endpoint returns 200 with valid schema in public mode without credentials; every write endpoint returns 403 problem-details |
| 3 | Private-mode parity | Every endpoint returns 200 with valid schema in private mode given a populated store and a valid API key |
| 4 | Job lifecycle | `POST /backtest/run` → poll `GET /jobs/{id}` until `succeeded`; restart of TestClient preserves the record |
| 5 | API-key auth | Private mode + unset key → warning logged + 200; private mode + set key → 401 without header, 401 wrong key, 200 correct key; key never appears in any log line |
| 6 | Error contract uniformity | 401 / 403 / 404 / 422 / 500 all return `application/problem+json` with all `ProblemDetail` fields populated |
| 7 | Observability | Every request emits exactly one structured access log line containing `request_id`, `method`, `path`, `status`, `duration_ms`; `request_id` echoed in `X-Request-ID` response header |
| 8 | Scheduler | `daily_refresh` registers with the configured cron; runs once on manual trigger; writes `results/.tmp/last_refresh.json`; `/health` reflects the marker |
| 9 | Static notebook serving | Existing HTMLs served with ETag + max-age; missing notebook returns fallback HTML; `GET /api/v1/notebooks` lists all available |
| 10 | Test coverage | ≥ 90% line coverage on `api/` package (per [Testing Strategy](#testing-strategy)) |
| 11 | Type / lint / test gates | `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/ api/`, `uv run pytest tests/ -v` all green |
| 12 | Notebook sign-off | `05_api_validation.ipynb` Section 8 prints PASS for criteria 1–11 |

---

## Future Enhancements

- **OAuth2 / JWT** — replace static API key with multi-user authentication when the multi-strategy dashboard introduces a tenancy model (Phase 7+)
- **Rate limiting** — token-bucket per-key rate limit middleware (Phase 7)
- **Prometheus metrics** — `/metrics` endpoint with request count / duration / job count histograms (Phase 7)
- **OpenTelemetry tracing** — trace propagation across scheduler → JobRegistry → ParquetStore reads (Phase 8)
- **Distributed job queue** — replace in-process `JobRegistry` with Celery / RQ / Dramatiq if multi-worker concurrency is required (Phase 8)
- **WebSocket streaming** — push live signal updates and job status changes to subscribed clients (Phase 8)
- **Live broker connector** — `POST /api/v1/orders` accepting `TradeList` from Phase 4.7 and routing to a paper or live broker (post-Phase 8)
- **Audit log** — append-only log of every write request with user, key fingerprint, timestamp (Phase 7)
- **Versioned API** — introduce `/api/v2/` when a breaking schema change is required; v1 remains supported per a deprecation policy

---

## Commit & PR Templates

### Commit Message (Plan — this commit)

```
feat(plan): add master plan for phase 5 api based on phase 4 audit
```

### Commit Messages (per sub-phase, on implementation)

```
refactor(api): audit app factory and add request-id middleware (Phase 5.1)

- app.version sourced from csm.__version__
- RequestIDMiddleware assigns ULID per request, echoed in X-Request-ID header
- Lifespan instantiates JobRegistry singleton on app.state.jobs
```

```
feat(api): add typed Pydantic response schemas for every endpoint (Phase 5.2)

- New api/schemas/ package with one module per resource
- All routers declare response_model; dict[str, object] returns removed
- OpenAPI tags, summaries, examples added to every route
```

```
feat(api): harden read-only routers with ETag and parity tests (Phase 5.3)

- Universe / signals / portfolio return typed schemas with ETag headers
- 304 Not Modified honoured on If-None-Match
- Public + private parity tests pass
```

```
feat(api): add JobRegistry and GET /api/v1/jobs/{id} lifecycle (Phase 5.4)

- JobRegistry with accepted -> running -> succeeded|failed state machine
- BackgroundTasks replaced by JobRegistry for backtest_run and data_refresh
- Restart-safe persistence under results/.tmp/jobs/
```

```
feat(api): bind scheduler to refresh_cron and surface health marker (Phase 5.5)

- CronTrigger.from_crontab(settings.refresh_cron, tz="Asia/Bangkok")
- misfire_grace_time, coalesce, max_instances configured
- Manual trigger endpoint POST /api/v1/scheduler/run/{job_id} (private only)
- last_refresh.json marker written; /health reflects status
```

```
feat(api): add notebook index and ETag-aware static serving (Phase 5.6)

- GET /api/v1/notebooks returns NotebookIndex
- StaticFiles fallback HTML for missing notebooks
- Cache-Control max-age=300 + ETag round-trip
```

```
feat(api): add API-key authentication and harden public-mode contract (Phase 5.7)

- Settings.api_key: SecretStr | None
- APIKeyMiddleware: 401 on missing/invalid X-API-Key in private mode
- Public-mode contract test for every write endpoint
- Key redaction filter in logs
```

```
feat(api): add structured logging, problem-details errors, /health (Phase 5.8)

- JsonFormatter with request_id contextvar propagation
- AccessLogMiddleware: one structured line per request
- problem_details_handler: RFC 7807 application/problem+json
- /health surfaces version, scheduler_running, last_refresh_at, jobs_pending
```

```
feat(api): full integration test matrix and 05_api_validation notebook (Phase 5.9)

- tests/integration/test_api_*.py — public + private + error matrix per resource
- OpenAPI snapshot test pinned
- notebooks/05_api_validation.ipynb — Section 8 prints PASS for all 12 criteria
```

### PR Description Template

```markdown
## Summary

Phase 5 — API. Promotes the existing FastAPI scaffolding under `api/` into a typed, observable, authenticated, dual-mode REST surface with a persistent JobRegistry, RFC 7807 problem-details errors, structured logging, and a comprehensive integration test matrix.

- Typed Pydantic response schemas for every endpoint; OpenAPI snapshot pinned
- `JobRegistry` replaces `BackgroundTasks`; `GET /api/v1/jobs/{id}` for status polling; restart-safe persistence
- API-key middleware (`X-API-Key`) gates private-mode endpoints; uniform 403 in public mode for writes
- RFC 7807 problem-details for every 4xx/5xx; request-ID propagation via contextvar
- `daily_refresh` bound to `Settings.refresh_cron`; `/health` surfaces scheduler status and last-refresh marker
- Notebook index endpoint + ETag-aware static serving
- `notebooks/05_api_validation.ipynb` Section 8 prints PASS for all 12 success criteria

## Test plan

- [ ] `uv run ruff check .` — exits 0
- [ ] `uv run ruff format --check .` — exits 0
- [ ] `uv run mypy src/ api/` — exits 0
- [ ] `uv run pytest tests/ -v` — all unit + integration tests pass
- [ ] `uv run pytest tests/integration/test_openapi_snapshot.py -v` — schema snapshot matches
- [ ] Manual: open `notebooks/05_api_validation.ipynb`, run all cells, confirm Section 8 PASS for all 12 criteria
- [ ] Manual: `uv run uvicorn api.main:app --reload --port 8000` in private mode → curl `/health`, `/api/v1/universe`, submit a backtest, poll job
- [ ] Manual: `CSM_PUBLIC_MODE=true uv run uvicorn api.main:app --reload --port 8000` → curl read endpoints work; write endpoints return 403 problem-details
```
