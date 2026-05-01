# Phase 5.4 — Write Routers & Job Lifecycle

**Feature:** Write Routers & Job Lifecycle
**Branch:** `feature/phase-5-api`
**Created:** 2026-04-30
**Status:** Complete — 2026-04-30
**Depends on:** Phase 5.3 (Read-Only Routers Hardening)

---

## Completion Notes

### Files Created
| File | Description |
|---|---|
| `api/routers/jobs.py` | New router: GET /api/v1/jobs/{job_id} (single job status) and GET /api/v1/jobs (filtered list, private mode only) |

### Files Modified
| File | Change |
|---|---|
| `api/jobs.py` | Full JobRegistry rewrite: per-kind async worker queues, ULID job IDs, atomic JSON persistence, load_all() classmethod for restart safety, cancel() support, shutdown() |
| `api/schemas/data.py` | RefreshResult: replaced refreshed/requested with job_id + JobStatus |
| `api/schemas/backtest.py` | BacktestRunResponse: changed status from str to JobStatus enum |
| `api/routers/data.py` | Rewrote POST handler: validates prerequisites then submits via JobRegistry; extracted _refresh_runner as standalone async function |
| `api/routers/backtest.py` | Replaced BackgroundTasks with JobRegistry; extracted _backtest_runner wrapping sync MomentumBacktest.run() in asyncio.to_thread() |
| `api/routers/__init__.py` | Added jobs_router export |
| `api/main.py` | Lifespan uses JobRegistry.load_all() for restart safety; added jobs.shutdown() in finally; registered jobs_router; added "/api/v1/jobs" to WRITE_PATHS |
| `tests/unit/test_api_schemas.py` | Updated TestRefreshResult and TestBacktestRunResponse to test new fields |
| `tests/integration/test_api_endpoints.py` | Added test for non-blocking data refresh in private mode and jobs list blocked in public mode |
| `tests/conftest.py` | Added features_latest and prices_latest to private_store; added .tmp/jobs directory creation to all client fixtures |

### Files Created (Tests)
| File | Description |
|---|---|
| `tests/integration/test_job_lifecycle.py` | 13 integration tests covering data refresh submission/polling, backtest lifecycle, job list filtering, public-mode gating, and restart safety |

### Test Results
- 595/595 tests pass (15 new tests: 2 schema + 13 integration)
- No regressions in existing tests

### Design Decisions
- **Per-kind async worker queues**: `asyncio.Queue` per JobKind with dedicated `asyncio.Task` workers. Different kinds run concurrently; same-kind jobs are strictly FIFO. This gives natural Semaphore(1) per kind behavior.
- **ULID for job IDs**: Uses the existing `python-ulid` dependency (Phase 5.1) for consistency with request IDs. Provides chronological ordering.
- **Atomic persistence**: Each state change writes to a `.tmp` file that is atomically renamed over the `.json` target. No partial writes.
- **Orphaned job recovery**: On `load_all()`, any job left in RUNNING state from a previous process is marked FAILED with "Process terminated before job completed".
- **Cancellation only from ACCEPTED**: Once a job starts running, it cannot be cancelled. The worker skips dequeued items whose status is CANCELLED.
- **Sync backtest in asyncio.to_thread()**: `MomentumBacktest.run()` is CPU-bound and synchronous — wrapping in `asyncio.to_thread()` keeps the event loop free.
- **Single job lookup NOT gated in public mode**: `GET /api/v1/jobs/{job_id}` returns 404 (not 403) in public mode since no jobs are ever created there. The list endpoint `GET /api/v1/jobs` IS gated (403) since it exposes execution history.
- **RefreshResult schema breaking change**: `refreshed`/`requested` fields replaced by `job_id`/`status`. The counts move to `JobRecord.summary` dict.

### Issues
- None.

---

## Summary

Replace ephemeral `BackgroundTasks` with a persistent `JobRegistry` state machine. The registry uses per-kind FIFO queues with dedicated async worker tasks, WAL-style JSON persistence under `results/.tmp/jobs/`, and restart-safe rehydration via `load_all()`. Both write endpoints (`POST /api/v1/data/refresh` and `POST /api/v1/backtest/run`) now return a job ID immediately instead of blocking. A new `GET /api/v1/jobs/{job_id}` endpoint enables status polling, and `GET /api/v1/jobs` provides filtered listing (private mode only).

## Deliverables

1. `api/jobs.py` — Full JobRegistry with submit, cancel, get, list, _persist, load_all, shutdown
2. `api/schemas/data.py` — RefreshResult with job_id + JobStatus
3. `api/schemas/backtest.py` — BacktestRunResponse with JobStatus enum
4. `api/routers/data.py` — Non-blocking submission via JobRegistry
5. `api/routers/backtest.py` — JobRegistry replaces BackgroundTasks; asyncio.to_thread for sync backtest
6. `api/routers/jobs.py` — GET /{job_id} and GET / (list) endpoints
7. `api/routers/__init__.py` — jobs_router added
8. `api/main.py` — load_all() in lifespan, shutdown in finally, WRITE_PATHS extended
9. `tests/unit/test_api_schemas.py` — Updated RefreshResult and BacktestRunResponse tests
10. `tests/integration/test_job_lifecycle.py` — 13 integration tests
11. `tests/integration/test_api_endpoints.py` — 2 new tests
12. `tests/conftest.py` — Extended private_store and client fixtures

## Quality Gate Results

```bash
uv run ruff check api/ tests/integration/test_job_lifecycle.py tests/integration/test_api_endpoints.py tests/unit/test_api_schemas.py  # PASS
uv run ruff format --check .  # PASS (140 files)
uv run mypy api/              # PASS (27 source files, no errors)
uv run pytest tests/ -v       # 595 passed
```

## AI Agent Prompt

```
You are implementing Phase 5.4 (Write Routers & Job Lifecycle) of the csm-set project.
This is a FastAPI REST API for the SET Cross-Sectional Momentum Strategy.

## Context
- Project root: /Users/sarat/Code/csm-set
- Branch: feature/phase-5-api
- Previous phase (5.3): read-only router hardening with ETag, retry, structured logging
- Reference: docs/plans/phase5_api/PLAN.md (Phase 5.4 section)
- Standards: .claude/knowledge/project-skill.md, .claude/playbooks/feature-development.md
  - Always `uv run` for commands
  - Async-first, Pydantic at boundaries, strict typing
  - No secrets in repo, timezone Asia/Bangkok

## Goals
1. Replace ephemeral BackgroundTasks with persistent JobRegistry state machine
2. Convert write endpoints to non-blocking: return job_id immediately, work runs async
3. Add GET /api/v1/jobs/{job_id} for status polling
4. Add GET /api/v1/jobs for filtered listing (private mode only)
5. Restart-safe persistence via WAL JSON under results/.tmp/jobs/
6. Integration tests covering full job lifecycle

## Tasks

### 1. Rewrite api/jobs.py — Full JobRegistry
- Per-kind asyncio.Queue with dedicated worker tasks
- async submit(kind, runner, **kwargs) -> JobRecord with ULID generation
- cancel(job_id) -> bool (only from ACCEPTED state)
- Atomic _persist via temp file + rename
- load_all(persistence_dir) classmethod: rehydrate from disk, mark orphaned RUNNING as FAILED
- shutdown(): cancel workers, await completion
- Runner signature: Callable[..., Awaitable[dict[str, Any]]]

### 2. Update api/schemas/data.py
- Replace refreshed/requested with job_id: str + status: JobStatus

### 3. Update api/schemas/backtest.py
- Change status: str to status: JobStatus

### 4. Rewrite api/routers/data.py
- Extract _refresh_runner(settings, store) -> dict as async function
- Handler validates prerequisites, submits via JobRegistry, returns immediately

### 5. Rewrite api/routers/backtest.py
- Remove BackgroundTasks
- Extract _backtest_runner(store, config) -> dict wrapping sync MomentumBacktest.run() in asyncio.to_thread()
- Submit via JobRegistry, return immediately

### 6. Create api/routers/jobs.py
- GET /api/v1/jobs/{job_id} -> JobRecord (404 if unknown)
- GET /api/v1/jobs?kind=&status=&limit= -> list[JobRecord] (private mode only)

### 7. Update api/routers/__init__.py
- Add jobs_router import and export

### 8. Update api/main.py
- Import and register jobs_router
- Add "/api/v1/jobs" to WRITE_PATHS
- Lifespan: JobRegistry.load_all(results_dir / ".tmp" / "jobs")
- Lifespan finally: await jobs.shutdown()

### 9. Update tests/unit/test_api_schemas.py
- TestRefreshResult: use job_id + status fields
- TestBacktestRunResponse: use JobStatus enum

### 10. Create tests/integration/test_job_lifecycle.py
- TestDataRefreshJob: submit, poll until terminal, verify 404
- TestBacktestJobLifecycle: submit, poll until terminal
- TestJobListEndpoint: list, kind filter, limit, public-mode 403, single job not blocked
- TestRestartSafety: submit, wait, load_all, verify record present

### 11. Update tests/integration/test_api_endpoints.py
- Add test for non-blocking data refresh in private mode
- Add test for jobs list blocked in public mode

### 12. Update tests/conftest.py
- Add features_latest and prices_latest to private_store
- Add .tmp/jobs directory creation in client fixtures

### 13. Quality gates
uv run ruff check . && uv run ruff format --check . && uv run mypy api/ && uv run pytest tests/ -v

### 14. Update documentation
- Create docs/plans/phase5_api/phase5.4_write_routers_and_job_lifecycle.md
- Update docs/plans/phase5_api/PLAN.md Phase 5.4 status to Complete

### 15. Commit
feat(api): add JobRegistry and GET /api/v1/jobs/{id} lifecycle (Phase 5.4)
```
