# Phase 5.1 — App Factory & Lifespan Audit

**Feature:** Production-grade FastAPI app factory hardening
**Branch:** `feature/phase-5-api`
**Created:** 2026-04-30
**Status:** Complete — 2026-04-30
**Depends on:** None (Phase 5.1 is the first sub-phase)

---

## Completion Notes

### Files Created
| File | Description |
|---|---|
| `api/jobs.py` | `JobRegistry` skeleton with `JobStatus`/`JobKind` enums and `JobRecord` model |
| `api/logging.py` | `RequestIDMiddleware` (ULID generation, `REQUEST_ID_CTX` contextvar, `X-Request-ID` header) |
| `api/errors.py` | Stub exception handlers (`http_exception_handler`, `general_exception_handler`) |
| `tests/unit/test_api_lifespan.py` | 12 unit tests across 5 test classes |

### Files Modified
| File | Change |
|---|---|
| `api/main.py` | `app.version` from `csm.__version__`; lifespan creates `JobRegistry`; `RequestIDMiddleware` registered before CORS; exception handlers registered; `/health` uses `csm.__version__` |
| `api/deps.py` | Added `get_jobs()` dependency provider |
| `pyproject.toml` | Added `python-ulid>=3` dependency |

### Test Results
- 12/12 Phase 5.1 unit tests pass
- 517/523 total unit tests pass (6 pre-existing failures in `test_fetch_history.py`)

### Issues
- Pre-existing integration tests in `tests/integration/test_api_endpoints.py` fail due to settings singleton import ordering in `tests/conftest.py` — unrelated to Phase 5.1 changes.
- Exception handlers use `starlette.exceptions.HTTPException` (not `fastapi.exceptions.HTTPException`) to catch routing 404s correctly.

## Summary

Validate and extend the existing `api/main.py` app factory and lifespan. Introduce request-ID middleware, register the `JobRegistry` as a lifespan-managed singleton, derive `app.version` from `csm.__version__`, and register global exception handler stubs.

## Deliverables

1. `app.version` reads from `csm.__version__` (already exists at `src/csm/__init__.py:3`)
2. `api/jobs.py` — skeleton `JobRegistry` class (full implementation in Phase 5.4)
3. `api/logging.py` — `RequestIDMiddleware` (Starlette `BaseHTTPMiddleware`) generating ULIDs, binding to `contextvars.ContextVar`, echoing in `X-Request-ID` response header
4. Lifespan extended to instantiate `JobRegistry` on `app.state.jobs`
5. `api/deps.py` — `get_jobs()` provider
6. `api/errors.py` — stub exception handlers for `HTTPException` and `Exception`
7. `api/main.py` — register `RequestIDMiddleware` before CORS, register exception handlers
8. `pyproject.toml` — add `python-ulid` dependency
9. Unit tests (5+ cases) in `tests/unit/test_api_lifespan.py`

## Step-by-Step Action Plan

### Step 1: Add `python-ulid` dependency

**File:** `pyproject.toml`
**Change:** Add `"python-ulid>=3"` to `dependencies`.

### Step 2: Create `api/jobs.py` — JobRegistry skeleton

**File:** `api/jobs.py` (NEW)
**Content:**
- `JobStatus` enum (`StrEnum`): `ACCEPTED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`
- `JobKind` enum (`StrEnum`): `DATA_REFRESH`, `BACKTEST_RUN`
- `JobRecord` Pydantic model with fields: `job_id`, `kind`, `status`, `accepted_at`, `started_at`, `finished_at`, `summary`, `error`, `request_id`
- `JobRegistry` class:
  - `__init__(self)` — initializes empty `_jobs: dict[str, JobRecord]`
  - `submit(self, kind, runner, **kwargs) -> JobRecord` — stub (raises `NotImplementedError` for now)
  - `get(self, job_id) -> JobRecord | None` — returns `self._jobs.get(job_id)`
  - `list(self, kind=None, status=None, limit=50) -> list[JobRecord]` — returns empty list

### Step 3: Create `api/logging.py` — RequestIDMiddleware

**File:** `api/logging.py` (NEW)
**Content:**
- `REQUEST_ID_CTX: ContextVar[str]` — request-scoped context variable
- `get_request_id() -> str` — reads from contextvar, returns `"N/A"` if not set
- `RequestIDMiddleware(BaseHTTPMiddleware)`:
  - `dispatch(request, call_next)`:
    1. Generate ULID via `ulid.new().str`
    2. Set `REQUEST_ID_CTX` token via `REQUEST_ID_CTX.set(request_id)`
    3. Call `await call_next(request)`
    4. Add `X-Request-ID` header to response with the request_id
    5. Reset contextvar via `REQUEST_ID_CTX.reset(token)`

### Step 4: Create `api/errors.py` — stub exception handlers

**File:** `api/errors.py` (NEW)
**Content:**
- `async def http_exception_handler(request, exc: HTTPException) -> JSONResponse`:
  - Returns `JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "request_id": get_request_id()})`
- `async def general_exception_handler(request, exc: Exception) -> JSONResponse`:
  - Logs the exception at ERROR level
  - Returns `JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": get_request_id()})`

### Step 5: Modify `api/deps.py` — add `get_jobs()`

**File:** `api/deps.py`
**Change:** Add `get_jobs()` dependency:
```python
from fastapi import Request

def get_jobs(request: Request) -> JobRegistry:
    return request.app.state.jobs
```

### Step 6: Modify `api/main.py` — integrate all changes

**File:** `api/main.py`
**Changes:**
1. Import `csm.__version__` → use `csm.__version__` instead of `"0.1.0"` in `FastAPI(version=...)`
2. Import `JobRegistry` from `api.jobs` → instantiate in lifespan: `app.state.jobs = JobRegistry()`
3. Import `RequestIDMiddleware` from `api.logging` → register via `app.add_middleware(RequestIDMiddleware)` BEFORE CORS
4. Import handlers from `api.errors` → register via `app.add_exception_handler(HTTPException, http_exception_handler)` and `app.add_exception_handler(Exception, general_exception_handler)`

**Middleware registration order (LIFO — last registered is innermost):**
```python
app.add_middleware(RequestIDMiddleware)   # outermost
app.add_middleware(CORSMiddleware, ...)   # middle
# @app.middleware("http") public_mode_guard — innermost (already at line 62)
```

### Step 7: Create unit tests

**File:** `tests/unit/test_api_lifespan.py` (NEW)
**Test cases:**
1. **`test_app_version_from_csm`** — `app.version == csm.__version__`
2. **`test_openapi_schema_shows_version`** — `/openapi.json` includes correct version from `csm.__version__`
3. **`test_lifespan_creates_job_registry`** — lifespan context manager sets `app.state.jobs` as `JobRegistry` instance
4. **`test_request_id_per_request`** — two sequential requests get different `X-Request-ID` values
5. **`test_request_id_header_in_response`** — response includes `X-Request-ID` header matching the request's ID
6. **`test_request_id_contextvar_reset_between_requests`** — `REQUEST_ID_CTX` is `"N/A"` between requests
7. **`test_http_exception_handler_returns_request_id`** — 404 response body includes `request_id` field
8. **`test_public_mode_guard_still_works`** — write endpoints return 403 in public mode
9. **`test_health_endpoint_returns_correct_version`** — `/health` returns `version == csm.__version__`

### Step 8: Update PLAN.md and phase plan

**Files to update:**
- `docs/plans/phase5_api/PLAN.md` — mark Phase 5.1 checkboxes, add progress notes
- `docs/plans/phase5_api/phase5.1_app_factory_lifespan_audit.md` — add completion date and notes

## Files Changed Summary

| File | Action | Description |
|---|---|---|
| `pyproject.toml` | Edit | Add `python-ulid>=3` dependency |
| `api/jobs.py` | New | `JobRegistry` skeleton, `JobStatus`, `JobKind`, `JobRecord` |
| `api/logging.py` | New | `RequestIDMiddleware` with contextvar, `get_request_id()` |
| `api/errors.py` | New | Stub exception handlers for `HTTPException`, `Exception` |
| `api/main.py` | Edit | Version from `csm.__version__`, lifespan extended, middleware + handlers registered |
| `api/deps.py` | Edit | Add `get_jobs()` dependency |
| `tests/unit/test_api_lifespan.py` | New | 9 unit tests |
| `docs/plans/phase5_api/PLAN.md` | Edit | Update Phase 5.1 status + progress |
| `docs/plans/phase5_api/phase5.1_app_factory_lifespan_audit.md` | Edit | Add completion notes |

## Quality Gates

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src/ api/ && uv run pytest tests/unit/test_api_lifespan.py -v
```

## Verification

1. `uv run pytest tests/unit/test_api_lifespan.py -v` — all 9 tests pass
2. `curl http://localhost:8000/openapi.json | jq '.info.version'` → `"0.1.0"` (from `csm.__version__`)
3. `curl -v http://localhost:8000/health` → verify `X-Request-ID` header present
4. `curl http://localhost:8000/api/v1/data/refresh -X POST` → 403 (public mode guard still active)
5. `curl http://localhost:8000/nonexistent` → 404 with `request_id` in body

## AI Agent Prompt

```
You are implementing Phase 5.1 (App Factory & Lifespan Audit) of the csm-set project.
This is a FastAPI REST API for the SET Cross-Sectional Momentum Strategy.

## Context
- Project root: /Users/sarat/Code/csm-set
- Branch: feature/phase-5-api
- Existing code to extend:
  - api/main.py — FastAPI app factory with lifespan, CORS, public_mode_guard, /health
  - api/deps.py — get_settings(), get_store(), set_store() providers
  - src/csm/__init__.py — already has __version__ = "0.1.0"
- Reference: docs/plans/phase5_api/PLAN.md (Phase 5.1 section)
- Standards: .claude/knowledge/project-skill.md, .claude/playbooks/feature-development.md
  - Always `uv run` for commands
  - Async-first, Pydantic at boundaries, strict typing
  - No secrets in repo, timezone Asia/Bangkok

## Tasks

### 1. Add python-ulid dependency
Add "python-ulid>=3" to dependencies in pyproject.toml, then run `uv lock`.

### 2. Create api/jobs.py — JobRegistry skeleton
- JobStatus (StrEnum): ACCEPTED, RUNNING, SUCCEEDED, FAILED, CANCELLED
- JobKind (StrEnum): DATA_REFRESH, BACKTEST_RUN
- JobRecord (BaseModel): job_id (str), kind (JobKind), status (JobStatus), accepted_at (datetime), started_at (datetime|None=None), finished_at (datetime|None=None), summary (dict[str, Any]=Field(default_factory=dict)), error (str|None=None), request_id (str|None=None)
- JobRegistry class: __init__ (empty _jobs dict), get(job_id)->JobRecord|None, list(kind=None,status=None,limit=50)->list[JobRecord]
- submit() method stub that raises NotImplementedError (full impl in Phase 5.4)
- Export JobRegistry in __all__

### 3. Create api/logging.py — RequestIDMiddleware
- REQUEST_ID_CTX: ContextVar[str] with default "N/A"
- get_request_id() -> str: returns REQUEST_ID_CTX.get()
- RequestIDMiddleware(BaseHTTPMiddleware):
  - dispatch: generate ULID via `import ulid; ulid.new().str`, set contextvar token, call_next, add X-Request-ID response header, reset contextvar
  - Use try/finally to ensure contextvar reset
- Export RequestIDMiddleware, get_request_id, REQUEST_ID_CTX in __all__

### 4. Create api/errors.py — stub exception handlers
- Import get_request_id from api.logging
- http_exception_handler(request, exc: HTTPException) -> JSONResponse:
  - Return {"detail": exc.detail, "request_id": get_request_id()} with exc.status_code
- general_exception_handler(request, exc: Exception) -> JSONResponse:
  - Log via logging.getLogger(__name__).exception("Unhandled exception")
  - Return {"detail": "Internal server error", "request_id": get_request_id()} with 500

### 5. Modify api/deps.py — add get_jobs()
- Import Request from fastapi, JobRegistry from api.jobs
- Add get_jobs(request: Request) -> JobRegistry: return request.app.state.jobs
- Add to __all__

### 6. Modify api/main.py
- Import __version__ from csm, use it for app.version instead of "0.1.0"
- Import JobRegistry from api.jobs — create in lifespan: app.state.jobs = JobRegistry()
- Import RequestIDMiddleware from api.logging — register via app.add_middleware(RequestIDMiddleware) BEFORE CORS
- Import http_exception_handler, general_exception_handler from api.errors
- Register via app.add_exception_handler(HTTPException, http_exception_handler)
- Register via app.add_exception_handler(Exception, general_exception_handler)
- Update /health to use csm.__version__ instead of "0.1.0"

### 7. Create tests/unit/test_api_lifespan.py
Use TestClient from fastapi.testclient. Import app from api.main.

Test cases:
- test_app_version_from_csm: assert app.version == csm.__version__
- test_openapi_schema_has_version: client.get("/openapi.json") → info.version == csm.__version__
- test_lifespan_creates_job_registry: assert isinstance(app.state.jobs, JobRegistry)
- test_request_id_header_present: response.headers has "x-request-id" (case-insensitive)
- test_request_ids_differ_per_request: two requests, different x-request-id values
- test_request_id_contextvar_between_requests: import REQUEST_ID_CTX, assert "N/A" between requests
- test_http_exception_includes_request_id: get nonexistent path, body has request_id
- test_public_mode_guard_still_403: POST /api/v1/data/refresh returns 403
- test_health_version_from_csm: /health response version == csm.__version__

### 8. Quality gates
uv run ruff check . && uv run ruff format . && uv run mypy src/ api/ && uv run pytest tests/unit/test_api_lifespan.py -v

### 9. Update documentation
- Update docs/plans/phase5_api/PLAN.md Phase 5.1 checkboxes to [x]
- Update docs/plans/phase5_api/phase5.1_app_factory_lifespan_audit.md status to Complete

### 10. Commit
Use conventional commit message:
refactor(api): audit app factory and add request-id middleware (Phase 5.1)

- app.version sourced from csm.__version__
- RequestIDMiddleware assigns ULID per request, echoed in X-Request-ID header
- Lifespan instantiates JobRegistry singleton on app.state.jobs
- Add get_jobs() dependency provider
- Register global exception handler stubs
```
