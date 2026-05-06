# Phase 1: Connection & Config

**Feature:** csm-set-adapter — Integration layer connecting csm-set to quant-infra-db
**Branch:** `feature/csm-set-adapter`
**Created:** 2026-05-06
**Status:** Complete
**Completed:** 2026-05-06
**Depends On:** `quant-infra-db` Phase 1–5 complete (external prerequisite)

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

Phase 1 establishes the connection surface and configuration foundation for the csm-set-adapter feature. It adds `asyncpg` and `motor` as dependencies, extends `Settings` with DB connection strings and a write-enable flag, joins the Docker Compose services to the external `quant-network`, creates the adapter package skeleton, implements a DB connectivity health check, and wires it into the `/health` endpoint.

After this phase:
- `uv sync` resolves cleanly with `asyncpg` and `motor`.
- `Settings` carries typed DSN fields and `db_write_enabled` (default `False`).
- `docker compose up` connects to `quant-network` and resolves `quant-postgres` / `quant-mongo` hostnames.
- `GET /health` reports `db.postgres` and `db.mongo` connectivity status.
- The `src/csm/adapters/` package skeleton is in place for Phases 2–4.

### Parent Plan Reference

- `docs/plans/feature_adapter/PLAN.md` — Master plan, Phase 1 section (lines 205–274)

---

## AI Prompt

The following prompt was used to generate this phase:

```
🎯 Objective
Implement Phase 1 — Connection & Config for the feature_adapter initiative in the csm-set project.
Follow these steps precisely:

1. Preparation: Read .claude/knowledge/project-skill.md and .claude/playbooks/feature-development.md.
   Review docs/plans/feature_adapter/PLAN.md focusing on Phase 1.

2. Planning: Draft a detailed implementation plan following docs/plans/examples/phase1-sample.md format.
   Save as docs/plans/feature_adapter/phase_1_connection_and_config.md.

3. Implementation: Implement all Phase 1 deliverables per the plan and project documentation.
   Follow project standards: type safety, async/await, Pydantic validation, error handling, import organization.

4. Documentation: Update PLAN.md and the phase plan with progress notes, completion status, and issues.

5. Commit: Single commit with standards-compliant message. All tests must pass.

📋 Context
- csm-set is a cross-sectional momentum strategy engine for SET (Stock Exchange of Thailand).
- The feature_branch is feature/csm-set-adapter.
- quant-infra-db containers (quant-postgres, quant-mongo) are reachable via Docker DNS on quant-network.
- Project rules: always uv run; async-first I/O via httpx; Pydantic at module boundaries; CSM_ env prefix via pydantic-settings.
- The existing Settings class in src/csm/config/settings.py uses model_config with env_prefix="CSM_", frozen=True.
- The existing HealthStatus model is in api/schemas/health.py with frozen ConfigDict.
- No src/csm/adapters/ directory exists yet — it must be created.

🔧 Requirements
Phase 1 deliverables:
1.1 Dependencies & Settings:
  - Add asyncpg>=0.29 and motor>=3.4 to pyproject.toml [project].dependencies
  - Extend Settings with: db_csm_set_dsn, db_gateway_dsn, mongo_uri (all str|None, default None), db_write_enabled (bool, default False)
  - Update .env.example with the new vars, annotated with comments
  - Unit test: confirm defaults and env parsing in tests/unit/config/test_settings.py

1.2 Docker Compose — join quant-network:
  - Add networks section to docker-compose.yml joining external quant-network
  - Mirror in docker-compose.private.yml

1.3 Adapter package skeleton + connectivity check:
  - Create src/csm/adapters/ package with __init__.py, health.py, empty postgres.py/mongo.py/gateway.py
  - Implement check_db_connectivity(settings) -> dict[str, str] in health.py using asyncpg + motor short-lived connections
  - Extend HealthStatus with db: dict[str, str] | None
  - Wire check_db_connectivity into GET /health in api/main.py
  - Unit test: tests/unit/adapters/test_health.py (mock both clients)
  - Integration test: tests/integration/adapters/test_health_io.py (infra_db marker)

Files to reference and/or modify: All files listed in File Changes section below.
```

---

## Scope

### In Scope (Phase 1)

| Component | Description | Status |
|---|---|---|
| `asyncpg` / `motor` deps | Added to `pyproject.toml` `[project].dependencies` | `[x]` |
| `Settings` DB fields | `db_csm_set_dsn`, `db_gateway_dsn`, `mongo_uri`, `db_write_enabled` | `[x]` |
| `.env.example` update | New DB vars with comments | `[x]` |
| Settings unit test | Confirm defaults, env parsing | `[x]` |
| Docker Compose network | Join external `quant-network` in both compose files | `[x]` |
| `src/csm/adapters/` package | `__init__.py`, `health.py`, empty `postgres.py`/`mongo.py`/`gateway.py` | `[x]` |
| `check_db_connectivity()` | Async health check using short-lived `asyncpg` + `motor` connections | `[x]` |
| `HealthStatus.db` field | `dict[str, str] \| None` added to health schema | `[x]` |
| `/health` wiring | `check_db_connectivity` called in health endpoint | `[x]` |
| Unit test (`test_health.py`) | Mock both clients; assert error reporting | `[x]` |
| Integration test (`test_health_io.py`) | `infra_db` marker; assert `ok` against real stack | `[x]` |

### Out of Scope (Phase 1)

- PostgresAdapter implementation (Phase 2)
- MongoAdapter implementation (Phase 3)
- GatewayAdapter implementation (Phase 4)
- AdapterManager / pipeline hooks (Phase 5)
- API history endpoints (Phase 6)
- Coverage gate on `src/csm/adapters/` (Phase 7)
- CI workflow for `infra_db` tests (Phase 7)

---

## Design Decisions

### 1. Short-lived connections for health check, not pool reuse

`check_db_connectivity()` creates fresh `asyncpg` and `motor` connections for each call and tears them down immediately. Rationale: (a) the health check runs before lifespan startup (when pools don't exist yet), (b) it can be called independently before deciding whether to enable write-back, (c) connection failures here don't affect pool state. The pools themselves (min=2, max=10) are created in Phases 2–4 when the adapter classes are built.

### 2. DSN fields use `str | None` with `exclude=True` in validation_alias

All DB DSN fields default to `None`. The `pydantic-settings` `env_prefix="CSM_"` is inherited from the existing model config, so the env vars are `CSM_DB_CSM_SET_DSN`, `CSM_DB_GATEWAY_DSN`, `CSM_MONGO_URI`, `CSM_DB_WRITE_ENABLED`. No additional validation is applied to DSN strings — `asyncpg` and `motor` will surface malformed URIs at connection time via the health check.

### 3. `db_write_enabled` defaults to `False`

Write-back is opt-in. When `False`, `check_db_connectivity()` skips all checks and returns `None`, and the `/health` response carries `"db": null`. This keeps csm-set's existing zero-config public-mode contract intact.

### 4. Docker network is `external: true`

The `quant-network` is created and managed by the `quant-infra-db` Compose stack. csm-set joins it as an external network — it never creates or destroys it. If the network doesn't exist at `docker compose up` time, Docker Compose surfaces a clear error.

### 5. `HealthStatus.db` is `dict[str, str] | None`, not a nested model

A flat `dict[str, str]` with keys `"postgres"` and `"mongo"` is intentionally simpler than a nested Pydantic model. The health endpoint is consumed by ops tooling (Docker healthcheck, monitoring dashboards) that prefers flat JSON. Values are `"ok"` or `"error:<message>"`.

### 6. Adapter package follows existing project structure

The `src/csm/adapters/` package mirrors the existing subpackage conventions: `__init__.py` re-exports public API, each adapter gets its own module, and health/connectivity lives in a dedicated `health.py` module. File size budget of ≤400 lines applies.

---

## Implementation Steps

### Step 1: Add dependencies to `pyproject.toml`

Add to `[project].dependencies`:
```
"asyncpg>=0.29",
"motor>=3.4",
```
Run `uv sync --all-groups` to resolve and lock.

### Step 2: Extend `Settings` with DB fields

In `src/csm/config/settings.py`, add four new fields to the `Settings` class:
```python
db_csm_set_dsn: str | None = Field(default=None, description="PostgreSQL DSN for db_csm_set.")
db_gateway_dsn: str | None = Field(default=None, description="PostgreSQL DSN for db_gateway.")
mongo_uri: str | None = Field(default=None, description="MongoDB connection URI.")
db_write_enabled: bool = Field(default=False, description="Enable DB write-back when True.")
```
These inherit the `CSM_` env prefix automatically. No custom validators needed — DSN validation happens at connection time.

### Step 3: Update `.env.example`

Append a new section after the scheduler line:
```env
# quant-infra-db connections (required when CSM_DB_WRITE_ENABLED=true)
CSM_DB_CSM_SET_DSN=postgresql://postgres:<pass>@quant-postgres:5432/db_csm_set
CSM_DB_GATEWAY_DSN=postgresql://postgres:<pass>@quant-postgres:5432/db_gateway
CSM_MONGO_URI=mongodb://quant-mongo:27017/
CSM_DB_WRITE_ENABLED=false
```

### Step 4: Add unit tests for new Settings fields

In `tests/unit/config/test_settings.py`, add tests:
- `test_db_write_enabled_defaults_to_false` — confirm `db_write_enabled` is `False` by default
- `test_db_dsn_fields_default_to_none` — confirm all three DSN fields default to `None`
- `test_db_write_enabled_from_env` — confirm `CSM_DB_WRITE_ENABLED=true` parses correctly
- `test_db_dsn_fields_from_env` — confirm DSN fields read from environment

### Step 5: Patch Docker Compose files

In both `docker-compose.yml` and `docker-compose.private.yml`, add a top-level `networks` section:
```yaml
networks:
  default:
    name: quant-network
    external: true
```

### Step 6: Create adapter package skeleton

Create `src/csm/adapters/` with:
- `__init__.py` — docstring, future `AdapterManager` re-export placeholder
- `health.py` — `check_db_connectivity()` implementation
- `postgres.py` — docstring placeholder for Phase 2
- `mongo.py` — docstring placeholder for Phase 3
- `gateway.py` — docstring placeholder for Phase 4

### Step 7: Implement `check_db_connectivity()`

In `src/csm/adapters/health.py`:
```python
async def check_db_connectivity(settings: Settings) -> dict[str, str] | None:
    """Check connectivity to quant-postgres and quant-mongo.

    Returns None when db_write_enabled is False.
    Returns {"postgres": "ok"|"error:<msg>", "mongo": "ok"|"error:<msg>"} otherwise.
    Uses short-lived connections — no pool reuse.
    """
```
Implementation uses `asyncpg.connect()` and `motor.AsyncIOMotorClient` with a short server-info ping, wrapped in try/except. Each check runs independently so one failure doesn't block the other.

### Step 8: Extend `HealthStatus` with `db` field

In `api/schemas/health.py`, add:
```python
db: dict[str, str] | None = Field(
    default=None,
    description="Database connectivity status. null when db_write_enabled=False.",
)
```

### Step 9: Wire into `/health` endpoint

In `api/main.py` health handler:
- Import `check_db_connectivity` from `csm.adapters.health`
- Call `await check_db_connectivity(settings)` 
- Pass result as `db=db_status` to `HealthStatus(...)`
- Guard with try/except so a health-check failure doesn't break the health endpoint itself

### Step 10: Write unit test for health check

In `tests/unit/adapters/test_health.py`:
- Test: when `db_write_enabled=False`, returns `None`
- Test: mock `asyncpg.connect` to raise; assert `{"postgres": "error:...", "mongo": "error:..."}`
- Test: mock both to succeed; assert `{"postgres": "ok", "mongo": "ok"}`
- Test: one succeeds, one fails — results are independent

### Step 11: Write integration test skeleton

In `tests/integration/adapters/test_health_io.py`:
- Marked `@pytest.mark.infra_db`
- Asserts `{"postgres": "ok", "mongo": "ok"}` against the real stack
- Skip if env vars not set (graceful when stack is down)

### Step 12: Run quality gates

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src/ && uv run pytest tests/ -v
```

All four must pass.

### Step 13: Update PLAN.md progress notes

Mark Phase 1 items as `[x]` complete in `docs/plans/feature_adapter/PLAN.md`, update the Current Status table.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `pyproject.toml` | MODIFY | Add `asyncpg>=0.29`, `motor>=3.4` to dependencies |
| `src/csm/config/settings.py` | MODIFY | Add 4 DB fields to `Settings` |
| `.env.example` | MODIFY | Add DB connection vars section |
| `tests/unit/config/test_settings.py` | MODIFY | Add tests for new Settings fields |
| `docker-compose.yml` | MODIFY | Add `networks` section joining `quant-network` |
| `docker-compose.private.yml` | MODIFY | Add `networks` section joining `quant-network` |
| `src/csm/adapters/__init__.py` | CREATE | Package init, future `AdapterManager` placeholder |
| `src/csm/adapters/health.py` | CREATE | `check_db_connectivity()` implementation |
| `src/csm/adapters/postgres.py` | CREATE | Empty skeleton for Phase 2 |
| `src/csm/adapters/mongo.py` | CREATE | Empty skeleton for Phase 3 |
| `src/csm/adapters/gateway.py` | CREATE | Empty skeleton for Phase 4 |
| `api/schemas/health.py` | MODIFY | Add `db: dict[str, str] \| None` to `HealthStatus` |
| `api/main.py` | MODIFY | Wire `check_db_connectivity` into `/health` |
| `tests/unit/adapters/test_health.py` | CREATE | Unit tests for health check (mocked clients) |
| `tests/integration/adapters/test_health_io.py` | CREATE | Integration test (infra_db marker) |

---

## Acceptance Criteria

- [x] `uv run python -c "from csm.config.settings import settings; print(settings.db_write_enabled)"` prints `False` with no error
- [x] `uv sync --all-groups` resolves cleanly with `asyncpg` and `motor`
- [x] `uv run mypy src/csm/config/settings.py` is clean
- [x] `uv run mypy src/csm/adapters/` is clean
- [x] `uv run ruff check .` is clean
- [x] `uv run ruff format --check .` is clean
- [x] `uv run pytest tests/unit/config/test_settings.py -v` is green (including new DB tests)
- [x] `uv run pytest tests/unit/adapters/test_health.py -v` is green
- [~] `docker compose up -d csm` succeeds when `quant-network` exists (requires quant-infra-db stack)
- [~] `docker compose exec csm ping -c 1 quant-postgres` exits 0 (requires quant-infra-db stack)
- [~] `docker compose exec csm ping -c 1 quant-mongo` exits 0 (requires quant-infra-db stack)
- [~] `curl http://localhost:8100/health` returns `"db": {"postgres": "ok", "mongo": "ok"}` when stack is up and `db_write_enabled=true` (requires quant-infra-db stack)
- [x] `curl http://localhost:8100/health` returns `"db": null` when `db_write_enabled=false` (verified: check_db_connectivity returns None when flag is off)

---

## Completion Notes

### Summary

Phase 1 complete. All deliverables implemented:

- **1.1 Dependencies & Settings:** `asyncpg>=0.29` and `motor>=3.4` added to `pyproject.toml`. Four new fields (`db_csm_set_dsn`, `db_gateway_dsn`, `mongo_uri`, `db_write_enabled`) added to `Settings` with `CSM_` env prefix. `.env.example` updated with commented DB vars.
- **1.2 Docker Compose:** Both `docker-compose.yml` and `docker-compose.private.yml` now join the external `quant-network`.
- **1.3 Adapter package + health check:** `src/csm/adapters/` package created with skeleton modules. `check_db_connectivity()` implemented with short-lived `asyncpg` + `motor` connections. `HealthStatus.db` field added. Wired into `/health` endpoint with try/except guard.

Quality gates all pass: ruff check, ruff format, mypy (strict, 49 files), pytest (846 passed, 1 skipped, 0 failed).

### Issues Encountered

1. **Mypy `type-arg` error for `AsyncIOMotorClient`.** Motor 3.7+ declares `AsyncIOMotorClient` as a generic type. Fixed by importing `Any` from `typing` and annotating as `AsyncIOMotorClient[Any]`. The `Any` import is safe because `from __future__ import annotations` makes it a string annotation at runtime.

2. **OpenAPI snapshot mismatch.** Adding `db: dict[str, str] | None` to `HealthStatus` changed the generated OpenAPI schema. Updated the snapshot at `tests/integration/__snapshots__/openapi.json` per the documented procedure in `test_openapi_snapshot.py`.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.7)
**Status:** Draft — awaiting implementation
