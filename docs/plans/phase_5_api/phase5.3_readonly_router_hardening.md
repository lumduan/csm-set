# Phase 5.3 — Read-Only Routers Hardening

**Feature:** Production hardening of read-only API endpoints
**Branch:** `feature/phase-5-api`
**Created:** 2026-04-30
**Status:** Complete — 2026-04-30
**Depends on:** Phase 5.2 (API Contract & Response Schemas)

---

## Completion Notes

### Files Created
| File | Description |
|---|---|
| `api/retry.py` | Generic async retry utility with exponential backoff + jitter |
| `api/schemas/params.py` | Pydantic models for strict input validation (extra="forbid") |
| `tests/integration/conftest.py` | Integration test fixtures (public_client alias, enriched tmp_results variants) |
| `tests/integration/test_api_universe.py` | 8 integration tests for GET /api/v1/universe |
| `tests/integration/test_api_signals.py` | 7 integration tests for GET /api/v1/signals/latest |
| `tests/integration/test_api_portfolio.py` | 11 integration tests for GET /api/v1/portfolio/current |

### Files Modified
| File | Change |
|---|---|
| `api/routers/universe.py` | ETag (content hash of symbol+sector list), retry on store.load, structured logging, 304 support, problem-detail error responses |
| `api/routers/signals.py` | ETag (content hash), retry on JSON reads and pipeline.load_latest, structured logging, 304 support, broader error catching |
| `api/routers/portfolio.py` | ETag (stable fields only, excluding dynamic as_of), retry on store.load and JSON reads, structured logging, 304 support, regime/breaker_state/equity_fraction from portfolio_state parquet key |
| `api/schemas/portfolio.py` | Added `regime`, `breaker_state`, `equity_fraction` fields with defaults |
| `tests/conftest.py` | Added `private_store`, `private_client`, `empty_store`, `empty_store_client` fixtures; patched api.main.settings and api.deps.settings for test isolation |
| `docs/plans/phase5_api/PLAN.md` | Phase 5.3 marked complete |

### Test Results
- 580/580 tests pass (26 new integration tests + all pre-existing tests)
- All 30 API integration tests pass (universe, signals, portfolio, endpoints)

### Design Decisions
- **Weak ETags** (`W/"<sha256>"`) — semantically correct for application-level caching, compatible with gzip/content-negotiation
- **No external retry dependency** — simple async retry with exp backoff + jitter, no tenacity dependency
- **`regime`/`breaker_state` as `str` not `Literal`** — tolerates enum additions in Phase 4 without API schema breakage
- **`portfolio_state` parquet key** — loaded if exists, defaults otherwise (no breaking change for stores without it)
- **Portfolio ETag excludes `as_of`** — the timestamp changes on every private-mode request; caching must be based on stable content (holdings, regime, weights)
- **Broader exception catching in signals** — `KeyError` from `store.load()` (missing feature key) is now properly caught and returns 500 instead of crashing

### Issues
- Empty Pydantic models (`extra="forbid"`) don't trigger query param validation with FastAPI's `Depends()` because there are no fields to bind. Kept the params module as documentation for future parameters.
- `api.main` and `api.deps` both import `settings` from `csm.config.settings` as local bindings — both must be patched in test fixtures for proper isolation. Added `api.deps.settings` patching alongside existing `api.main.settings` patching.

---

## Summary

Harden the three read-only routers (universe, signals, portfolio) for production use. Add ETag caching with `If-None-Match` / `304 Not Modified` support, retry logic for all file and store I/O, structured logging at INFO/WARNING/ERROR levels, problem-detail error responses, and comprehensive integration tests covering public mode, private mode, and error paths.

## Deliverables

1. `api/retry.py` — `retry_async` and `retry_sync` with exp backoff + jitter, `RetryExhausted` exception
2. `api/schemas/params.py` — Pydantic models for future query parameter validation
3. `api/schemas/portfolio.py` — Added `regime`, `breaker_state`, `equity_fraction` fields
4. `api/routers/universe.py` — ETag, retry, structured logging, 304, problem-detail errors
5. `api/routers/signals.py` — ETag, retry, structured logging, 304, problem-detail errors
6. `api/routers/portfolio.py` — ETag (stable fields), regime/breaker_state, retry, structured logging, 304
7. `tests/conftest.py` — private_store, private_client, empty_store_client fixtures
8. `tests/integration/conftest.py` — Shared integration fixtures
9. `tests/integration/test_api_universe.py` — 8 tests (public/private 200/404, ETag)
10. `tests/integration/test_api_signals.py` — 7 tests (public/private 200/404, ETag)
11. `tests/integration/test_api_portfolio.py` — 11 tests (public/private 200/404, regime/breaker, ETag)

## Quality Gate Results

```bash
uv run ruff check .           # PASS (pre-existing notebook issues only)
uv run ruff format --check .  # PASS
uv run mypy api/ tests/       # 0 errors in api/ (31 pre-existing in tests/unit/)
uv run pytest tests/ -v       # 580 passed
```

## AI Agent Prompt

```
You are implementing Phase 5.3 (Read-Only Routers Hardening) of the csm-set project.
This is a FastAPI REST API for the SET Cross-Sectional Momentum Strategy.

## Context
- Project root: /Users/sarat/Code/csm-set
- Branch: feature/phase-5-api
- Previous phase (5.2): typed Pydantic response schemas, OpenAPI metadata
- Reference: docs/plans/phase5_api/PLAN.md (Phase 5.3 section)
- Standards: .claude/knowledge/project-skill.md, .claude/playbooks/feature-development.md
  - Always `uv run` for commands
  - Async-first, Pydantic at boundaries, strict typing
  - No secrets in repo, timezone Asia/Bangkok

## Goals
1. Harden universe, signals, and portfolio routers with ETag caching, retry logic, structured logging
2. Add strict input validation via Pydantic query parameter models
3. Surface regime and breaker_state from Phase 4 modules in portfolio endpoint
4. Add comprehensive integration tests: public + private + error matrix per router

## Tasks

### 1. Create api/retry.py
Generic async retry utility:
- `retry_async(fn, *args, max_retries=3, base_delay=1.0, max_delay=10.0, retryable=..., **kwargs)` — retries an async callable
- `retry_sync(fn, *args, ...)` — runs sync callable via asyncio.to_thread with retry
- `RetryExhausted(operation, attempts, last_exception)` — raised when all retries fail
- Exponential backoff: delay = min(base_delay * 2^attempt, max_delay) * (1 + random * 0.1)
- Log each retry at WARNING, exhausted at ERROR

### 2. Create api/schemas/params.py
Pydantic models with extra="forbid", frozen=True for:
- UniverseParams, SignalParams, PortfolioParams
(Note: empty models don't trigger FastAPI query validation; kept for future parameter docs)

### 3. Update api/schemas/portfolio.py
Add to PortfolioSnapshot:
- regime: str = Field(default="NEUTRAL")
- breaker_state: str = Field(default="NORMAL")
- equity_fraction: float = Field(default=1.0, ge=0.0, le=1.5)

### 4. Harden api/routers/universe.py
- ETag from sorted symbol list + sector list SHA-256 → W/"<hash>"
- If-None-Match check → 304 Not Modified
- retry_sync(store.load, "universe_latest", retryable=(OSError, StoreError))
- Structured logging at INFO (success), WARNING (not found), ERROR (I/O failure)
- Problem-detail error responses
- Request + Response parameters for header access

### 5. Harden api/routers/signals.py
- ETag from model_dump_json SHA-256 → W/"<hash>"
- If-None-Match → 304
- Public mode: retry_async for JSON read
- Private mode: retry_sync for pipeline.load_latest, catch KeyError
- Structured logging
- Problem-detail errors

### 6. Harden api/routers/portfolio.py
- ETag from stable fields (exclude dynamic as_of timestamp)
- If-None-Match → 304
- Load portfolio_state parquet key for regime/breaker_state/equity_fraction
- retry_sync for store.load, retry_async for JSON reads
- Structured logging
- Problem-detail errors

### 7. Add test fixtures to tests/conftest.py
- private_store: populated ParquetStore (universe_latest, portfolio_current, portfolio_state)
- private_client: TestClient with private mode + populated store
- empty_store: empty ParquetStore
- empty_store_client: TestClient with empty store for 404 tests
- Fix api.main.settings and api.deps.settings patching for test isolation

### 8. Create tests/integration/conftest.py
- public_client alias
- tmp_results_signals_full, tmp_results_portfolio_full, tmp_results_malformed

### 9. Create integration test files
- test_api_universe.py: public 404, public idempotent, private 200, private schema, private 404, ETag header, ETag 304, ETag stale
- test_api_signals.py: public 200, public schema, public idempotent, private error, ETag header, ETag 304, ETag stale
- test_api_portfolio.py: public 200, public schema, public idempotent, private 200, private schema, private regime/breaker, private 404, ETag header, ETag 304, ETag stale, ETag consistent

### 10. Quality gates
uv run ruff check . && uv run ruff format --check . && uv run mypy api/ tests/ && uv run pytest tests/ -v

### 11. Update documentation
- Create docs/plans/phase5_api/phase5.3_readonly_router_hardening.md
- Update docs/plans/phase5_api/PLAN.md Phase 5.3 status to Complete

### 12. Commit
Use conventional commit:
feat(api): harden read-only routers with ETag, retry, and error handling (Phase 5.3)
```
