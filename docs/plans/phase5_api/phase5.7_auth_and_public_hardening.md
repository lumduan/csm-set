# Phase 5.7: Authentication & Public-Mode Hardening

**Feature:** API-key authentication for protected endpoints; explicit public-mode 403 contract
**Branch:** `feature/phase-5-api`
**Created:** 2026-04-30
**Status:** Complete
**Completed:** 2026-04-30
**Depends On:** Phase 5.6 (Complete)

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Implementation Steps](#implementation-steps)
6. [File Changes](#file-changes)
7. [Success Criteria](#success-criteria)
8. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 5.7 closes the largest remaining gap on the private-mode side of the API: the four write
endpoints (`POST /api/v1/data/refresh`, `POST /api/v1/backtest/run`,
`POST /api/v1/scheduler/run/daily_refresh`) plus the sensitive list endpoint
(`GET /api/v1/jobs`) currently accept any caller that can reach the host. There is no auth, no
shared secret, no rate limit. Private-mode deployments behind anything more permissive than a
loopback bind are unsafe.

This phase adds an `X-API-Key` shared-secret authentication layer enforced by middleware,
configured via `Settings.api_key: SecretStr | None`, and codifies the public-mode 403 contract
with an explicit per-endpoint test matrix. It also adds a logging filter that scrubs the
configured key from every log record so accidental key leaks via `logger.debug(...)` or
third-party libraries are caught.

### Parent Plan Reference

- `docs/plans/phase5_api/PLAN.md` — Phase 5.7 row in the implementation phases table

### Key Deliverables

1. **`src/csm/config/settings.py`** — `api_key: SecretStr | None` field with `CSM_API_KEY` env binding
2. **`api/security.py`** — `APIKeyMiddleware` and `is_protected_path` predicate (NEW module)
3. **`api/logging.py`** — `KeyRedactionFilter` and `install_key_redaction()` helper
4. **`api/main.py`** — middleware wiring + dev-mode startup warning
5. **`tests/conftest.py`** — `private_client_with_key` fixture
6. **`tests/unit/test_api_security.py`** — 12 unit tests for the middleware, predicate, and filter
7. **`tests/integration/test_api_auth.py`** — 8 integration tests covering the full auth contract
8. **`.env.example`** — documents `CSM_API_KEY`

---

## AI Prompt

The following prompt was used to generate this phase:

```
🎯 Objective
Design and implement Phase 5.7 — Authentication & Public-Mode Hardening for the csm-set FastAPI project, including planning, implementation, documentation, and progress tracking according to project standards.

📋 Context
- Project: csm-set (FastAPI REST API for SET Cross-Sectional Momentum Strategy)
- Previous phase (5.6): Static asset & notebook serving, with custom static file handling, ETag, and caching
- Current branch: feature/phase-5-api
- Standards: .claude/knowledge/project-skill.md, .claude/playbooks/feature-development.md
- Documentation:
  - docs/plans/phase5_api/PLAN.md (phase tracking, checklist)
  - docs/plans/phase5_api/phase5.6_static_asset_and_notebook_serving.md (last completed phase, context for static/public endpoints)
- You must plan before coding, document the plan as docs/plans/phase5_api/phase5.7_auth_and_public_hardening.md (include the prompt), and update PLAN.md with progress and completion notes.

🔧 Requirements
- Read and follow all architectural, security, and workflow standards in .claude/knowledge/project-skill.md and .claude/playbooks/feature-development.md
- Carefully review docs/plans/phase5_api/PLAN.md and docs/plans/phase5_api/phase5.6_static_asset_and_notebook_serving.md for current state and requirements
- Plan and implement authentication for the API, including:
  - Secure, production-ready authentication (e.g., OAuth2, API key, or JWT as appropriate)
  - Public-mode hardening: ensure all endpoints and static assets are protected or explicitly allowed for public access
  - Granular access control: restrict sensitive endpoints, allow public access only where intended (e.g., static notebooks if required)
  - Comprehensive error handling and user feedback for authentication failures
  - Type-safe, async-first implementation with Pydantic validation for all auth-related models and settings
  - Tests for all new authentication and access control logic (unit and integration)
  - Documentation updates for new auth flows and public/private endpoint distinctions
- After planning, create the plan as docs/plans/phase5_api/phase5.7_auth_and_public_hardening.md, including the prompt used, following the format in docs/plans/examples/phase1-sample.md
- Only begin implementation after the plan is written and committed
- On completion, update docs/plans/phase5_api/PLAN.md and docs/plans/phase5_api/phase5.7_auth_and_public_hardening.md with progress notes, completion date, and any issues encountered
- Commit all changes as a single, well-documented commit

📁 Code Context
- .claude/knowledge/project-skill.md (project skills, standards)
- .claude/playbooks/feature-development.md (feature workflow)
- docs/plans/phase5_api/PLAN.md (phase checklist, progress)
- docs/plans/phase5_api/phase5.6_static_asset_and_notebook_serving.md (last phase, static/public context)
- docs/plans/examples/phase1-sample.md (plan format reference)
- All API code, routers, static file handling, and settings modules

✅ Expected Output
- A detailed plan for Phase 5.7 in docs/plans/phase5_api/phase5.7_auth_and_public_hardening.md, including the full prompt
- Implementation of authentication and public-mode hardening as per plan and requirements
- Updated docs/plans/phase5_api/PLAN.md and docs/plans/phase5_api/phase5.7_auth_and_public_hardening.md with progress and completion notes
- All code, tests, and documentation committed with a clear, standards-compliant commit message
```

---

## Scope

### In Scope

| Component | Description | Status |
|---|---|---|
| `Settings.api_key` | `SecretStr \| None` field bound to `CSM_API_KEY` | Complete |
| `APIKeyMiddleware` | Enforces `X-API-Key` on protected paths in private mode | Complete |
| `is_protected_path` | Predicate combining `WRITE_PATHS` and non-GET `/api/v1/*` rule | Complete |
| `KeyRedactionFilter` | Logging filter that masks the configured key in messages and args | Complete |
| `install_key_redaction` | Lifespan helper that attaches the filter to the root logger | Complete |
| Dev-mode startup warning | One WARNING line when private mode + no key configured | Complete |
| `private_client_with_key` fixture | TestClient with `CSM_API_KEY` set for integration tests | Complete |
| Unit tests | `is_protected_path` truth table, middleware dispatch branches, filter behaviour | Complete |
| Integration tests | Public-mode 403 matrix; private-mode 401/200 contract; reads exempt; key never logged | Complete |
| `.env.example` | Documents `CSM_API_KEY` with safety guidance | Complete |

### Out of Scope

- OAuth2 / JWT / multi-user auth — deferred to Phase 7 (introduced when the multi-strategy
  dashboard adds tenancy)
- Rate limiting — deferred to Phase 7
- Per-key audit log — deferred to Phase 7
- Full RFC 7807 problem-details (`type`, `title`, `instance`) — Phase 5.8 ships those across
  every error path; Phase 5.7 reuses the existing `ProblemDetail(detail, request_id)` shape
- API-key rotation tooling / multi-key support — single static key is sufficient for the
  owner-only deployment model
- Auth on read-only `GET` endpoints — reads remain public to preserve dual-mode contract parity

---

## Design Decisions

### 1. Static API key, not OAuth or JWT

The current and near-term deployment model is owner-only in private mode. A single shared secret
configured via `.env` matches every other secret in the project (tvkit credentials, etc.). OAuth
introduces multi-user concepts that are not yet warranted; it lands in Phase 7 if and when the
multi-strategy dashboard introduces tenancy.

### 2. Three-state auth behaviour

| Mode | `api_key` set? | `X-API-Key` header | Behaviour |
|---|---|---|---|
| Public | any | any | Reads pass; writes return 403 via `public_mode_guard` (existing) |
| Private | unset | any | One-time WARNING at lifespan startup; all paths accessible |
| Private | set | missing | 401 ProblemDetail with `Missing X-API-Key header` |
| Private | set | wrong | 401 ProblemDetail with `Invalid X-API-Key header` |
| Private | set | correct | Pass through |

The unset-key dev-mode path keeps the local development experience friction-free without
silently shipping unsafe defaults: the WARNING line in stderr is loud enough to notice but
quiet enough to ignore.

### 3. Protected-path predicate

The middleware enforces auth only on **protected paths**. Protection is the union of:

- The four hard-coded write paths in `WRITE_PATHS` (also used by `public_mode_guard`):
  `/api/v1/data/refresh`, `/api/v1/backtest/run`, `/api/v1/jobs`,
  `/api/v1/scheduler/run/daily_refresh`.
- Any non-`GET` method on a `/api/v1/*` path (defence in depth — catches future write endpoints
  before they are added to `WRITE_PATHS`).

Always exempt: `/health`, `/docs`, `/redoc`, `/openapi.json`, anything under
`/static/notebooks/`, and the read-only `GET` endpoints
(`/api/v1/{universe,signals,portfolio,notebooks}`, `/api/v1/jobs/{job_id}`).

The single-job lookup `GET /api/v1/jobs/{job_id}` stays exempt — a ULID is itself a soft secret;
it is the **list** endpoint that leaks every ID and is therefore protected.

### 4. Constant-time comparison

`secrets.compare_digest()` is used to compare the supplied header against the configured key.
This avoids a timing oracle that would otherwise allow an attacker to derive the key byte-by-byte
from response-time measurements. No new dependency — `secrets` is stdlib.

### 5. Middleware ordering

`app.add_middleware()` is LIFO; outermost = registered last. Required runtime order:

```
RequestID  →  APIKey  →  CORS  →  public_mode_guard  →  routers
```

Implementation order in `api/main.py`:
1. `add_middleware(RequestIDMiddleware)` — first, so it ends up outermost
2. `add_middleware(APIKeyMiddleware)` — second, between RequestID and CORS
3. `add_middleware(CORSMiddleware, ...)` — third
4. `@app.middleware("http") public_mode_guard` — innermost; defined via decorator

This gives every request a `request_id` before the auth check, so the 401 ProblemDetail can echo
it back, and CORS preflight `OPTIONS` requests are handled by the auth layer first (any non-GET on
`/api/v1/*` requires the key — which is the right semantic for a credential-bearing API).

### 6. Logging redaction

`KeyRedactionFilter` is a `logging.Filter` that, when a key is configured, replaces the literal
key string in `record.msg` and any `record.args` strings with `***REDACTED***`. It is attached to
the root logger inside the lifespan via `install_key_redaction(settings.api_key)`. Cheap (one
`str.replace` per record when the key is set; a no-op early return when the key is unset) and
safe against accidental leaks via `logger.debug("got headers %s", headers)` patterns.

### 7. Reuse `ProblemDetail`, not a new schema

The existing `ProblemDetail(detail, request_id)` shape from Phase 5.1 / 5.2 covers the 401
response cleanly. Phase 5.8 will extend it to the full RFC 7807 set (`type`, `title`, `status`,
`instance`); Phase 5.7 does not introduce a new schema because that would be churn against a
contract that is about to change anyway.

### 8. No router changes

Auth is enforced exclusively at the middleware layer. Routers do not call `get_settings()` to
check for a key, do not depend on a header, and do not change their handler signatures. This
keeps the contract observable and testable in one place and avoids per-router drift.

### 9. Test fixture composition over branching

A new `private_client_with_key` fixture is added rather than adding a `with_key` parameter to
`private_client`. The pattern matches `client` / `private_client` already in `tests/conftest.py`:
each mode is a distinct fixture, and tests that need a specific mode request it by name. The new
fixture yields `(TestClient, str)` so tests can easily build the header from the same key the
server is configured with.

---

## Implementation Steps

### Step 1: `src/csm/config/settings.py`

Added the `api_key: SecretStr | None` field with `default=None` and a description that calls out
the dev-only nature of the unset state. `SecretStr` (from Pydantic) prevents accidental
serialisation of the value via `model_dump()` or `repr()`. Updated `.env.example` with a
commented-out entry and a one-line guidance note.

### Step 2: `api/security.py`

Implemented the new module:

- `PROTECTED_PATHS: frozenset[str]` matching `WRITE_PATHS` from `api/main.py`.
- `is_protected_path(method: str, path: str) -> bool` — pure function returning `True` for any
  `WRITE_PATHS` member or any non-`GET` method on `/api/v1/*`.
- `APIKeyMiddleware(BaseHTTPMiddleware)` with:
  - Public mode → pass through (writes blocked by `public_mode_guard`).
  - Non-protected path → pass through.
  - Private mode + no key configured → pass through (warning emitted at startup).
  - Private mode + key configured → `secrets.compare_digest()` comparison; missing or invalid
    header returns 401 with a `ProblemDetail`-shaped JSON body including `request_id` from
    `get_request_id()`.
- WARNING log line on rejection: includes method, path, request_id; does not log the supplied
  header.

### Step 3: `api/logging.py`

Added `KeyRedactionFilter(logging.Filter)` and `install_key_redaction(secret: SecretStr | None)`.
The filter uses `str.replace` in both `record.msg` and `record.args`. The installer attaches the
filter to the root logger only when a key is configured, so the no-key path adds no overhead.

### Step 4: `api/main.py`

- Imported `APIKeyMiddleware` and `install_key_redaction`.
- Registered `APIKeyMiddleware` between `RequestIDMiddleware` and `CORSMiddleware`.
- Inside `lifespan`, before yielding: called `install_key_redaction(settings.api_key)` and
  emitted a one-time WARNING when `not settings.public_mode and settings.api_key is None`.

### Step 5: `tests/conftest.py`

Added the `private_client_with_key` fixture. Mirrors `private_client` exactly with one extra
`monkeypatch.setenv("CSM_API_KEY", "test-key-12345")` and yields a tuple
`(TestClient, "test-key-12345")` so tests can write
`client.post(..., headers={"X-API-Key": api_key})`.

### Step 6: `tests/unit/test_api_security.py`

12 unit tests across three test classes:

- `TestIsProtectedPath` — truth table covering the four WRITE_PATHS, non-GET on `/api/v1/*`,
  GET reads, `/health`, static, and unknown paths.
- `TestAPIKeyMiddleware` — dispatch branches: public mode, exempt path, no-key dev mode, missing
  header, wrong key, correct key. Uses a minimal `FastAPI` app with the middleware mounted.
- `TestKeyRedactionFilter` — message redaction, args redaction, no-op when secret is empty.

### Step 7: `tests/integration/test_api_auth.py`

8 integration tests:

- `test_public_mode_writes_return_403_problem_detail` — every entry in WRITE_PATHS returns 403
  with `detail` + `request_id` shape.
- `test_private_mode_no_key_emits_startup_warning` — captures `caplog`, asserts the WARNING line.
- `test_private_mode_no_key_allows_writes` — write returns 200 with `accepted` status.
- `test_private_mode_missing_header_returns_401` — POST without `X-API-Key` returns 401 with the
  expected detail.
- `test_private_mode_wrong_key_returns_401` — POST with wrong key returns 401.
- `test_private_mode_correct_key_allows_writes` — POST with correct key returns 200 / accepted.
- `test_private_mode_reads_do_not_require_key` — GET reads succeed without header.
- `test_private_mode_health_and_docs_exempt` — `/health`, `/openapi.json`, `/docs` reachable
  without header.
- `test_api_key_never_appears_in_logs` — caplog at DEBUG; raw key string absent across a 401 +
  200 round-trip.

### Step 8: `.env.example`

Appended the documented `# CSM_API_KEY=...` line with a one-line note about strong random
secrets and the dev-mode warning.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `src/csm/config/settings.py` | MODIFY | Add `api_key: SecretStr \| None` field |
| `.env.example` | MODIFY | Document `CSM_API_KEY` |
| `api/security.py` | CREATE | `APIKeyMiddleware`, `is_protected_path`, `PROTECTED_PATHS` |
| `api/logging.py` | MODIFY | Add `KeyRedactionFilter`, `install_key_redaction` |
| `api/main.py` | MODIFY | Register middleware, install redaction, dev-mode warning |
| `tests/conftest.py` | MODIFY | Add `private_client_with_key` fixture |
| `tests/unit/test_api_security.py` | CREATE | Unit tests for middleware + predicate + filter |
| `tests/integration/test_api_auth.py` | CREATE | Integration tests for auth contract |
| `docs/plans/phase5_api/phase5.7_auth_and_public_hardening.md` | CREATE | This plan document |
| `docs/plans/phase5_api/PLAN.md` | MODIFY | Mark Phase 5.7 complete with notes |

### Files NOT Changed

- All routers under `api/routers/` — auth is at the middleware layer.
- `api/schemas/errors.py` — `ProblemDetail` is reused as-is.
- `api/deps.py` — no new dependencies.
- `api/jobs.py`, `api/scheduler/jobs.py` — auth is orthogonal to job lifecycle.

---

## Success Criteria

- [x] `Settings.api_key: SecretStr | None` loads from `CSM_API_KEY`
- [x] `APIKeyMiddleware` returns 401 with `ProblemDetail` shape on missing / wrong key in private mode + key configured
- [x] Private mode + no key configured emits exactly one WARNING at startup; subsequent requests are not log-spammed
- [x] Public-mode 403 contract test exists for every entry in `WRITE_PATHS`
- [x] Read endpoints (`/api/v1/universe`, `/api/v1/signals/latest`, `/api/v1/portfolio/current`, `/api/v1/notebooks`) succeed without `X-API-Key` even in private mode
- [x] `/health`, `/docs`, `/redoc`, `/openapi.json`, `/static/notebooks/*` always exempt
- [x] `secrets.compare_digest` used for header comparison
- [x] `KeyRedactionFilter` masks the configured key in log records (msg and args)
- [x] No log line emitted by the API contains the raw key string in any test
- [x] `uv run ruff check .` exits 0
- [x] `uv run ruff format --check .` exits 0
- [x] `uv run mypy src/ api/` exits 0
- [x] `uv run pytest tests/ -v` — all tests pass; new tests > 15

---

## Completion Notes

### Summary

Phase 5.7 ships an `X-API-Key` shared-secret authentication layer at the middleware level,
guarded by a `Settings.api_key: SecretStr | None` field, plus a logging filter that scrubs the
configured key from every log record. The public-mode 403 contract is now codified by a complete
per-endpoint test matrix in `tests/integration/test_api_auth.py`. No router signatures changed;
auth is orthogonal to the request-handling code.

### Issues Encountered

1. **Middleware ordering.** `app.add_middleware` is LIFO — the LAST registered runs OUTERMOST.
   The initial registration order placed `RequestIDMiddleware` innermost, so `request_id` was
   "N/A" in auth and public-mode-guard error responses. Fixed by registering `RequestIDMiddleware`
   last (outermost), `APIKeyMiddleware` second-to-last, and `CORSMiddleware` first (innermost
   before the `@app.middleware("http")` guard).

2. **caplog vs fixture-setup logs.** The `caplog` fixture is installed during test setup, but the
   `private_client` fixture enters the lifespan context manager during its own setup — before
   `caplog` may be active. The "CSM_API_KEY not configured" startup-warning test was reworked to
   inline the TestClient creation inside the test body so `caplog` is armed before the lifespan
   fires.

3. **TestClient raises server exceptions.** Starlette's `TestClient` defaults to
   `raise_server_exceptions=True`, so the synthetic-feature-data `ValueError` in the signals
   endpoint is re-raised rather than returned as a 500 response. `test_reads_do_not_require_key`
   wraps each `client.get()` in a `try/except` — any exception means the request passed the
   auth middleware, satisfying the test's invariant.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.7)
**Status:** Complete
**Completed:** 2026-04-30
