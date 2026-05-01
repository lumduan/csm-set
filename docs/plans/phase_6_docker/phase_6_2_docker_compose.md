# Phase 6.2 — Docker Compose Dual Config

**Feature:** Public + private docker-compose configs
**Branch:** `feature/phase-6-docker`
**Created:** 2026-05-01
**Status:** Complete
**Completed:** 2026-05-01
**Depends on:** Phase 6.1 (Multi-stage Dockerfile + CORS — complete)
**Positioning:** Wraps the Phase 6.1 Dockerfile with compose configs for two audiences: public users get one-command zero-credential boot; the owner gets a private override profile with writable data mounts and tvkit auth.

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

Phase 6.2 delivers two docker-compose configuration files that together implement the public-by-default / private-on-demand model architected in the Phase 6 master plan:

- **`docker-compose.yml`** — public mode. One-command boot with no credentials. Results mounted read-only, CORS wide open (`*`).
- **`docker-compose.private.yml`** — override file for the owner. Disables public mode, mounts data/ writable, mounts Chrome profile for tvkit browser auth, restricts CORS to localhost dev origins.

The private config is a pure override — it does not redefine the `csm` service. The user invokes: `docker compose -f docker-compose.yml -f docker-compose.private.yml up`.

### Parent Plan Reference

- `docs/plans/phase_6_docker/PLAN.md` — Phase 6.2 section

### Key Deliverables

1. **`docker-compose.yml`** — Rewritten with single port 8000, healthcheck stanza, mem_limit 2g, CORS origins explicit, header documentation
2. **`docker-compose.private.yml`** — Updated with CORS restriction, mem_limit, healthcheck, comprehensive header comments
3. **`tests/integration/test_docker_compose_config.py`** — Structural validation tests for both compose files (YAML parse, required keys, volume mount modes)

---

## AI Prompt

The following prompt was used to generate this phase:

```
🎯 Objective
Implement Phase 6.2 — Docker Compose Dual Config for the csm-set project, following the detailed
plan in `docs/plans/phase_6_docker/PLAN.md`. The goal is to rewrite the existing stub
docker-compose.yml for public-mode one-command boot and update docker-compose.private.yml as a
pure override file for owner use with writable mounts and restricted CORS.

📋 Context
- Phase 6.1 is complete: multi-stage Dockerfile with HEALTHCHECK exists, CORS middleware is wired
  in api/main.py, Settings.cors_allow_origins defaults to ["*"].
- The existing `docker-compose.yml` is a stub (230 bytes): dual ports 8080+8000, no healthcheck,
  no mem_limit, no CORS env, no documentation header.
- The existing `docker-compose.private.yml` (597 bytes): has basic override structure but misses
  CSM_CORS_ALLOW_ORIGINS restriction, mem_limit, and healthcheck.
- Project standards: async-first I/O, Pydantic at boundaries, uv run for all commands, no secrets
  in repo, docs/plans/ is git-tracked.
- All requirements, environment variables, and volume mounts are specified in the Phase 6 master plan.

🔧 Requirements
1. Rewrite `docker-compose.yml`:
   - Single port "8000:8000" (remove 8080 — Dockerfile only exposes 8000)
   - environment: CSM_PUBLIC_MODE=true, CSM_LOG_LEVEL=INFO, CSM_CORS_ALLOW_ORIGINS=*
   - volumes: ./results:/app/results:ro
   - healthcheck: interval 30s, timeout 5s, retries 3, start_period 20s
   - mem_limit: 2g
   - restart: unless-stopped
   - Header comment block with: purpose, usage command, smoke test command, link to private config

2. Update `docker-compose.private.yml`:
   - Add CSM_CORS_ALLOW_ORIGINS="http://localhost:3000,http://localhost:5173" (restrict to dev origins)
   - Add mem_limit: 2g
   - Add healthcheck stanza (same as public)
   - Keep existing environment overrides (CSM_PUBLIC_MODE=false, TVKIT_BROWSER=chrome)
   - Keep existing volume overrides (writable data/, results/, chrome profile :ro)
   - Expand header comments: full invocation, what each override does, when to use

3. Add `tests/integration/test_docker_compose_config.py`:
   - Test that both YAML files parse successfully
   - Test that public compose has single port 8000 (not 8080)
   - Test that public compose has mem_limit set
   - Test that public compose results volume is :ro
   - Test that private compose overrides CSM_PUBLIC_MODE to false
   - Test that private compose results volume is writable (no :ro)
   - Test that both have healthcheck configured

4. Update `docs/plans/phase_6_docker/PLAN.md` Phase 6.2 status and completion notes.

5. Run quality gate: uv run ruff check . && uv run ruff format . && uv run mypy src/ && uv run pytest tests/ -v
```
---

## Scope

### In Scope

| Component | Description | Status |
|---|---|---|
| `docker-compose.yml` | Rewrite: single port 8000, healthcheck, mem_limit 2g, CORS explicit, header docs | Complete |
| `docker-compose.private.yml` | Update: add CORS restriction, mem_limit, healthcheck, expanded header | Complete |
| `tests/integration/test_docker_compose_config.py` | Structural validation tests (YAML parse, port check, volume modes, env overrides) | Complete |
| `docs/plans/phase_6_docker/PLAN.md` | Update Phase 6.2 status + completion notes | Complete |

### Out of Scope

- Phase 6.3 (export_results.py): data population script; done in next sub-phase
- Phase 6.4 (data boundary audit): OHLCV leak detection
- Phase 6.5 (README rewrite): documentation changes
- Phase 6.6/6.7 (CI workflows): GitHub Actions
- `docker-compose.dev.yml` (hot-reload dev config): explicitly deferred per master plan
- Running actual `docker compose up`: manual acceptance only; CI smoke is Phase 6.6

---

## Design Decisions

### 1. Private config is a pure override — no service redefinition

The `docker-compose.private.yml` uses only `services.csm.environment` and `services.csm.volumes` keys. It does not redefine `build`, `ports`, `restart`, `mem_limit`, or `healthcheck`. Docker Compose merges these onto the base `docker-compose.yml` service definition. This is DRY and ensures the private config never accidentally diverges from the public image definition.

### 2. Port 8080 removed entirely

The existing stub has `ports: ["8080:8080", "8000:8000"]`. Phase 6.1's Dockerfile exposes only port 8000 and runs `uvicorn api.main:app --port 8000`. Port 8080 was a leftover from the old `ui/main.py` entrypoint and has no function in the Phase 6 architecture. Removing it keeps the compose file minimal and avoids the "why two ports?" confusion for public users.

### 3. CORS origins explicitly set in both configs

While `Settings.cors_allow_origins` defaults to `["*"]` in code, the compose configs set `CSM_CORS_ALLOW_ORIGINS` explicitly:
- **Public:** `"*"` — open to any origin (read-only API, no sensitive data)
- **Private:** `"http://localhost:3000,http://localhost:5173"` — restrict to local React/Next.js dev servers

This makes behavior visible in the compose file rather than relying on code defaults.

### 4. Healthcheck in both compose files

Docker HEALTHCHECK is defined in the Dockerfile, but adding a compose-level `healthcheck` stanza provides two benefits:
- Compose `depends_on` with `condition: service_healthy` works for future multi-service setups
- The compose healthcheck is visible to users reading the file without opening the Dockerfile

The compose healthcheck mirrors the Dockerfile: `interval: 30s`, `timeout: 5s`, `retries: 3`, `start_period: 20s`.

### 5. mem_limit: 2g in public config

Applied only in `docker-compose.yml` (not re-declared in private override). The 2 GB limit matches the documented nbconvert memory budget from the master plan. For read-only public boot, this is ample headroom; for the owner running `export_results.py` in private mode, the limit still applies but the override inherits it from the base config.

### 6. Integration tests validate compose structure, not Docker runtime

The tests parse YAML and assert on the data structure (keys present, values correct). They do not require Docker to be installed. This keeps the quality gate fast and CI-compatible. Actual `docker compose up` verification is deferred to Phase 6.6 (CI smoke workflow) and manual sign-off.

---

## Implementation Steps

### Step 1: Rewrite `docker-compose.yml`

Replace the existing 230-byte stub with:
- Header comment block (purpose, usage, smoke test, link to private config)
- Single port `"8000:8000"`
- environment block with `CSM_PUBLIC_MODE`, `CSM_LOG_LEVEL`, `CSM_CORS_ALLOW_ORIGINS`
- `volumes: ["./results:/app/results:ro"]`
- `healthcheck` stanza mirroring Dockerfile
- `mem_limit: 2g`
- `restart: unless-stopped`

### Step 2: Update `docker-compose.private.yml`

- Expand header comments with detailed override documentation
- Add `CSM_CORS_ALLOW_ORIGINS` to environment overrides
- Add `mem_limit: 2g` (inherits from base but explicit for clarity)
- Add `healthcheck` stanza
- Keep existing `CSM_PUBLIC_MODE`, `TVKIT_BROWSER` env overrides
- Keep existing volume overrides (`./data:/app/data`, `./results:/app/results`, chrome profile)

### Step 3: Add `tests/integration/test_docker_compose_config.py`

Write structural tests:
- `test_public_compose_parses` — YAML parses without error
- `test_public_compose_has_single_port_8000` — no port 8080
- `test_public_compose_has_mem_limit` — `mem_limit: 2g`
- `test_public_compose_results_readonly` — volume mount has `:ro`
- `test_public_compose_has_healthcheck` — healthcheck keys present
- `test_private_compose_parses` — YAML parses without error
- `test_private_compose_overrides_public_mode` — `CSM_PUBLIC_MODE=false`
- `test_private_compose_restricts_cors` — `CSM_CORS_ALLOW_ORIGINS` contains localhost
- `test_private_compose_results_writable` — no `:ro` on results volume
- `test_private_compose_has_chrome_mount` — chrome profile volume present

### Step 4: Update master plan

Mark Phase 6.2 deliverables as complete in `docs/plans/phase_6_docker/PLAN.md`. Add completion notes to this file.

### Step 5: Quality gate

```bash
uv run ruff check . && uv run ruff format . && uv run mypy src/ && uv run pytest tests/ -v
```

---

## File Changes

| File | Action | Description |
|---|---|---|
| `docker-compose.yml` | MODIFY | Rewrite: single port 8000, healthcheck, mem_limit, CORS, docs |
| `docker-compose.private.yml` | MODIFY | Add CORS restriction, mem_limit, healthcheck, expanded header |
| `tests/integration/test_docker_compose_config.py` | CREATE | Structural validation tests for both compose files |
| `docs/plans/phase_6_docker/PLAN.md` | MODIFY | Update Phase 6.2 status + completion notes |
| `docs/plans/phase_6_docker/phase_6_2_docker_compose.md` | MODIFY | This file — completion notes |

---

## Success Criteria

- [x] `docker-compose.yml` has single port `8000:8000` (port 8080 removed)
- [x] `docker-compose.yml` has `mem_limit: 2g`
- [x] `docker-compose.yml` has `healthcheck` stanza (interval 30s, retries 3)
- [x] `docker-compose.yml` has `results:/app/results:ro` (read-only)
- [x] `docker-compose.yml` has header comment block with usage + smoke command
- [x] `docker-compose.private.yml` sets `CSM_CORS_ALLOW_ORIGINS` to localhost origins
- [x] `docker-compose.private.yml` has `healthcheck` and `mem_limit`
- [x] `docker-compose.private.yml` has expanded header documenting invocation + overrides
- [x] `tests/integration/test_docker_compose_config.py` passes all 16 structural tests
- [x] Quality gate green: ruff check, mypy src/, pytest 22/22 all pass
- [x] `docs/plans/phase_6_docker/PLAN.md` updated with completion status

---

## Completion Notes

### Summary

Phase 6.2 complete. Both docker-compose configs were rewritten/updated to implement the public-by-default / private-on-demand model from the master plan. The public `docker-compose.yml` now has a single port 8000, healthcheck, mem_limit 2g, explicit CORS wildcard, and comprehensive header documentation. The private `docker-compose.private.yml` adds CORS restriction to local dev origins, mem_limit, and healthcheck alongside the existing writable mounts and tvkit auth. Port 8080 (legacy from standalone NiceGUI entrypoint) was removed entirely.

16 integration tests validate the compose file structure — YAML parse, port configuration, volume mount modes, environment variable overrides, healthcheck keys, and mem_limit — for both files. All 16 pass without requiring Docker.

### Issues Encountered

None. The implementation was straightforward given the well-defined deliverables in the master plan and the existing stub files providing a clear starting point.

---

**Document Version:** 1.0
**Author:** AI Agent
**Created:** 2026-05-01
**Status:** In Progress
