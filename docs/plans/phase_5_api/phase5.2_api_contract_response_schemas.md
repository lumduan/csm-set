# Phase 5.2 — API Contract & Response Schemas

**Feature:** Typed Pydantic response schemas for all API endpoints
**Branch:** `feature/phase-5-api`
**Created:** 2026-04-30
**Status:** Complete — 2026-04-30
**Depends on:** Phase 5.1 (App Factory & Lifespan Audit)

---

## Completion Notes

### Files Created
| File | Description |
|---|---|
| `api/schemas/__init__.py` | Package entry point; re-exports all 15 schema classes |
| `api/schemas/universe.py` | `UniverseItem` (extra="allow"), `UniverseSnapshot` |
| `api/schemas/signals.py` | `SignalRow` (extra="allow"), `SignalRanking` |
| `api/schemas/portfolio.py` | `Holding`, `PortfolioSnapshot` (extra="allow") |
| `api/schemas/backtest.py` | `BacktestRunResponse` |
| `api/schemas/data.py` | `RefreshResult` |
| `api/schemas/jobs.py` | Re-exports `JobKind`, `JobRecord`, `JobStatus` from `api.jobs` |
| `api/schemas/notebooks.py` | `NotebookEntry`, `NotebookIndex` (stubs for Phase 5.6) |
| `api/schemas/errors.py` | `ProblemDetail` (matches Phase 5.1 handler shape) |
| `api/schemas/health.py` | `HealthStatus` |
| `tests/unit/test_api_schemas.py` | 26 unit tests across 11 test classes |

### Files Modified
| File | Change |
|---|---|
| `api/routers/universe.py` | `response_model=UniverseSnapshot`; Pydantic return; OpenAPI metadata |
| `api/routers/signals.py` | `response_model=SignalRanking`; Pydantic return; OpenAPI metadata |
| `api/routers/portfolio.py` | `response_model=PortfolioSnapshot`; unified public/private return; OpenAPI metadata |
| `api/routers/backtest.py` | `response_model=BacktestRunResponse`; Pydantic return; OpenAPI metadata |
| `api/routers/data.py` | `response_model=RefreshResult`; Pydantic return; OpenAPI metadata |
| `api/main.py` | Health endpoint: `response_model=HealthStatus`, OpenAPI metadata |

### Test Results
- 26/26 Phase 5.2 schema unit tests pass
- 12/12 Phase 5.1 lifespan unit tests still pass
- 38/38 total unit tests pass

### Design Decisions
- **`ConfigDict(extra="allow")`** on `UniverseItem`, `SignalRow`, `PortfolioSnapshot` — accommodates dynamic DataFrame columns and variable signal sets without over-constraining the schema
- **No `BacktestRunRequest` wrapper** — `BacktestConfig` from `src.csm.research.backtest` is reused directly as the request body
- **Portfolio public/private unification** — both code paths return `PortfolioSnapshot`; public mode populates `summary_metrics`, private mode populates `holdings`
- **`ProblemDetail` shape** matches the Phase 5.1 handler stubs (`detail` + `request_id`); full RFC 7807 fields land in Phase 5.8

### Issues
- None.

## Summary

Replace every `dict[str, object]` return type across 5 routers + `/health` with typed Pydantic v2 response models. Create the `api/schemas/` package (10 modules). Add OpenAPI metadata — `summary`, `description`, `responses` with examples — to every endpoint.

## Deliverables

1. `api/schemas/__init__.py` — re-exports all 15 schema classes
2. `api/schemas/universe.py` — `UniverseItem(extra="allow")`, `UniverseSnapshot`
3. `api/schemas/signals.py` — `SignalRow(extra="allow")`, `SignalRanking`
4. `api/schemas/portfolio.py` — `Holding`, `PortfolioSnapshot(extra="allow")`
5. `api/schemas/backtest.py` — `BacktestRunResponse`
6. `api/schemas/data.py` — `RefreshResult`
7. `api/schemas/jobs.py` — re-exports from `api.jobs`
8. `api/schemas/notebooks.py` — `NotebookEntry`, `NotebookIndex`
9. `api/schemas/errors.py` — `ProblemDetail`
10. `api/schemas/health.py` — `HealthStatus`
11. All 5 routers updated with `response_model`, Pydantic returns, OpenAPI metadata
12. `/health` endpoint updated with `response_model=HealthStatus`, OpenAPI metadata
13. `tests/unit/test_api_schemas.py` — 26 round-trip unit tests

## Quality Gate Results

```bash
uv run ruff check .           # PASS
uv run ruff format --check .  # PASS
uv run mypy api/ tests/       # PASS
uv run pytest tests/unit/ -v  # 38/38 PASS (26 schema + 12 lifespan)
```

## AI Agent Prompt

```
You are implementing Phase 5.2 (API Contract & Response Schemas) of the csm-set project.
This is a FastAPI REST API for the SET Cross-Sectional Momentum Strategy.

## Context
- Project root: /Users/sarat/Code/csm-set
- Branch: feature/phase-5-api
- Previous phase (5.1): app factory audit, request-id middleware, JobRegistry skeleton, exception handler stubs
- Reference: docs/plans/phase5_api/PLAN.md (Phase 5.2 section)
- Standards: .claude/knowledge/project-skill.md, .claude/playbooks/feature-development.md
  - Always `uv run` for commands
  - Async-first, Pydantic at boundaries, strict typing
  - No secrets in repo, timezone Asia/Bangkok

## Goals
1. Replace every `dict[str, object]` return type with typed Pydantic v2 response models
2. Create `api/schemas/` package with one module per resource
3. Add OpenAPI tags, summaries, descriptions, and response examples to every endpoint
4. Ensure all routers declare `response_model` and return Pydantic instances

## Tasks

### 1. Create api/schemas/ package
Create 10 modules under api/schemas/:

- `__init__.py` — re-exports all schema classes
- `universe.py` — UniverseItem (symbol: str, extra="allow"), UniverseSnapshot (items: list[UniverseItem], count: int)
- `signals.py` — SignalRow (symbol: str, extra="allow"), SignalRanking (as_of: str, rankings: list[SignalRow])
- `portfolio.py` — Holding (symbol, weight: float ge=0 le=1, sector: str|None=None), PortfolioSnapshot (as_of: str, holdings: list[Holding], summary_metrics: dict[str, float]=default_factory=dict, extra="allow")
- `backtest.py` — BacktestRunResponse (job_id: str, status: str)
- `data.py` — RefreshResult (refreshed: int ge=0, requested: int ge=0)
- `jobs.py` — Re-exports JobKind, JobRecord, JobStatus from api.jobs
- `notebooks.py` — NotebookEntry (name, path, size_bytes ge=0, last_modified), NotebookIndex (items: list[NotebookEntry])
- `errors.py` — ProblemDetail (detail: str, request_id: str)
- `health.py` — HealthStatus (status: str, version: str, public_mode: bool)

Use ConfigDict(frozen=True) on all models. Use extra="allow" on UniverseItem, SignalRow, and PortfolioSnapshot to accept dynamic DataFrame columns.

### 2. Update all 5 routers
For each router in api/routers/:
- Add `response_model=` to the decorator
- Transform the return value to construct a Pydantic instance instead of a dict
- Add `summary=`, `description=`, `responses={}` with 200 example and 4xx ProblemDetail models

Particular care for:
- universe.py: construct UniverseItem list from frame.to_dict(orient="records"), wrap in UniverseSnapshot
- signals.py: both public and private mode paths must return SignalRanking. Extract as_of/rankings from public JSON, construct SignalRow list from private DataFrame rows
- portfolio.py: public mode parses summary.json into summary_metrics dict; private mode constructs Holding list from portfolio_current DataFrame. Both return PortfolioSnapshot.
- backtest.py/data.py: straightforward Pydantic return

### 3. Update api/main.py health endpoint
- response_model=HealthStatus
- summary="Service health check", description
- responses={200: example}

### 4. Create tests/unit/test_api_schemas.py
One round-trip test per schema class: construct -> model_dump -> re-parse -> assert equal.
Include extra="allow" tests proving dynamic fields survive round-trip.
Test StrEnum values from api.jobs re-exports.

### 5. Quality gates
uv run ruff check . && uv run ruff format --check . && uv run mypy api/ tests/ && uv run pytest tests/unit/ -v

### 6. Update documentation
- Create docs/plans/phase5_api/phase5.2_api_contract_response_schemas.md
- Update docs/plans/phase5_api/PLAN.md Phase 5.2 status to Complete

### 7. Commit
Use conventional commit:
feat(api): add typed Pydantic response schemas for every endpoint (Phase 5.2)

- New api/schemas/ package with 10 modules, 15 schema classes
- All routers declare response_model; dict[str, object] returns removed
- OpenAPI tags, summaries, examples added to every route
- 26 schema unit tests + 12 lifespan tests all pass
```
