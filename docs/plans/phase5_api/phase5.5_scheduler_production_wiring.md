# Phase 5.5: Scheduler Production Wiring

**Feature:** Phase 5 API
**Branch:** `feature/phase-5-api`
**Created:** 2026-04-30
**Status:** Complete
**Completed:** 2026-04-30
**Depends On:** Phase 5.4 (Complete) — JobRegistry, job routers, job lifecycle

## Table of Contents

- [Overview](#overview)
- [AI Prompt](#ai-prompt)
- [Scope](#scope)
- [Design Decisions](#design-decisions)
- [Implementation Steps](#implementation-steps)
- [File Changes](#file-changes)
- [Success Criteria](#success-criteria)
- [Completion Notes](#completion-notes)

## Overview

Phase 5.4 built the `JobRegistry` — an in-process async job state machine with FIFO queues, atomic JSON persistence, and per-kind workers. The scheduler (`api/scheduler/jobs.py`) was scaffolded with a bare `trigger="cron"` and the `daily_refresh` function was written but not production-hardened.

Phase 5.5 wires everything together:

- Binds the cron expression from `Settings.refresh_cron` using `CronTrigger.from_crontab`
- Adds misfire_grace_time=3600, coalesce=True, max_instances=1 for missed-run safety
- Writes a `last_refresh.json` marker file (for the extended `/health` endpoint in Phase 5.8)
- Adds failure-safe logging (errors logged at ERROR, scheduler stays alive)
- Exposes `POST /api/v1/scheduler/run/{job_id}` manual trigger endpoint (private mode only)
- `daily_refresh` is refactored to return `dict[str, Any]`, making it a valid JobRegistry runner

**Parent Plan Reference:** `docs/plans/phase5_api/PLAN.md`

### Key Deliverables

1. `api/scheduler/jobs.py` — refactored with CronTrigger, marker file, failure-safe wrapper
2. `api/routers/scheduler.py` — NEW: manual trigger endpoint
3. `api/routers/__init__.py` — exports `scheduler_router`
4. `api/main.py` — extended WRITE_PATHS, scheduler router included
5. `tests/unit/test_scheduler_jobs.py` — 11 unit tests
6. `tests/integration/test_scheduler_trigger.py` — 5 integration tests

## AI Prompt

```text
🎯 Objective
Design and implement Phase 5.5 — Scheduler Production Wiring for the csm-set FastAPI project, following the project's advanced engineering standards and workflow. This includes planning, implementation, documentation, and progress tracking, with a focus on robust, async, type-safe, and production-grade scheduler integration.

📋 Context
- Project: csm-set (FastAPI REST API for SET Cross-Sectional Momentum Strategy)
- Previous phase (5.4): Persistent JobRegistry, async job lifecycle, routers for job polling/listing, restart-safe WAL, full test coverage
- Current branch: feature/phase-5-api
- Standards: .claude/knowledge/project-skill.md (engineering principles), .claude/playbooks/feature-development.md (feature workflow)
- Documentation: 
  - docs/plans/phase5_api/PLAN.md (phase roadmap, requirements)
  - docs/plans/phase5_api/phase5.4_write_routers_and_job_lifecycle.md (last completed phase, for context)
- All code must be async-first, type-safe, Pydantic-validated, and fully tested
- Documentation and planning must be updated as part of the workflow

🔧 Requirements
- Carefully review .claude/knowledge/project-skill.md and .claude/playbooks/feature-development.md before starting
- Read and understand docs/plans/phase5_api/PLAN.md, focusing on Phase 5.5 — Scheduler Production Wiring
- Review docs/plans/phase5_api/phase5.4_write_routers_and_job_lifecycle.md for context on job lifecycle and registry
- Plan the implementation in detail before coding, following the format in docs/plans/examples/phase1-sample.md
- Create a plan markdown file at docs/plans/phase5_api/phase5.5_scheduler_production_wiring.md, including the prompt used
- Implement the scheduler wiring according to the plan
- Update docs/plans/phase5_api/PLAN.md and docs/plans/phase5_api/phase5.5_scheduler_production_wiring.md with progress notes
- Commit all changes with a clear, standards-compliant message
```

## Scope

### In Scope (Phase 5.5)

| Component | Description | Status |
|---|---|---|
| `api/scheduler/jobs.py` | CronTrigger parametrization, marker file, failure-safe wrapper, runner contract | Complete |
| `api/routers/scheduler.py` | NEW: `POST /api/v1/scheduler/run/{job_id}` manual trigger endpoint | Complete |
| `api/routers/__init__.py` | Export `scheduler_router` | Complete |
| `api/main.py` | Extend WRITE_PATHS, include scheduler_router | Complete |
| `tests/unit/test_scheduler_jobs.py` | 11 unit tests: cron config, misfire policies, runner contract, marker file, exception handling | Complete |
| `tests/integration/test_scheduler_trigger.py` | 5 integration tests: trigger lifecycle, validation, public-mode gating, marker file | Complete |

### Out of Scope (Phase 5.5)

- `/health` endpoint extension (Phase 5.8) — marker file written now, read later
- Authentication middleware (Phase 5.7)
- Additional scheduler job types beyond `daily_refresh`

## Design Decisions

1. **`daily_refresh` refactored into a JobRegistry-compatible runner.** The function now returns `dict[str, Any]` so it can be submitted via `JobRegistry.submit()`. The APScheduler wrapper calls it and logs the result but discards the return value. This avoids duplicating the refresh logic.

2. **Reuse `RefreshResult` schema for the manual trigger response.** Both `POST /api/v1/data/refresh` and `POST /api/v1/scheduler/run/{job_id}` return `{job_id, status}`. Using the same schema avoids unnecessary duplication.

3. **Marker file at `results/.tmp/last_refresh.json`.** Written atomically (temp file + rename, same pattern as `JobRegistry._persist`) on successful refresh. Contains `timestamp` (ISO 8601 UTC), `symbols_fetched`, `duration_seconds`, `failures`.

4. **WRITE_PATHS uses exact path matching.** The middleware checks `request.url.path in WRITE_PATHS` (set membership, not prefix). Entry added: `"/api/v1/scheduler/run/daily_refresh"`.

5. **Failure must not crash the scheduler.** The APScheduler wrapper catches all exceptions, logs at ERROR, and allows subsequent cron ticks to fire. The JobRegistry worker already handles runner exceptions gracefully.

6. **`_job_wrapper` is a closure over `settings` and `store`.** APScheduler calls job functions with no arguments, so the closure pattern is necessary and intentional.

## Implementation Steps

1. **Refactor `api/scheduler/jobs.py`** — Changed `daily_refresh` return type to `dict[str, Any]`. Added marker file write with atomic temp+rename. Hardened `_job_wrapper` with try/except. Replaced bare `trigger="cron"` with `CronTrigger.from_crontab` and misfire/coalesce/max_instances parameters.

2. **Create `api/routers/scheduler.py`** — Single `POST /run/{job_id}` endpoint. Validates `job_id` against `frozenset({"daily_refresh"})`. Submits via `JobRegistry.submit(JobKind.DATA_REFRESH, daily_refresh, ...)`. Returns `RefreshResult`.

3. **Wire router into app** — Added `scheduler_router` export in `api/routers/__init__.py`. Imported and included in `api/main.py`. Added `"/api/v1/scheduler/run/daily_refresh"` to `WRITE_PATHS`.

4. **Write unit tests** — 11 tests in `tests/unit/test_scheduler_jobs.py`: `TestCreateSchedulerConfig` (6 tests for cron/misfire/public-mode), `TestDailyRefreshRunner` (4 tests for runner contract/marker), `TestSchedulerWrapper` (1 test for exception safety).

5. **Write integration tests** — 5 tests in `tests/integration/test_scheduler_trigger.py`: trigger lifecycle, invalid job_id validation, public-mode gating, poll-to-terminal, marker file persistence.

## File Changes

| File | Action | Description |
|---|---|---|
| `api/scheduler/jobs.py` | MODIFY | CronTrigger, marker file, failure-safe wrapper, return summary dict |
| `api/routers/scheduler.py` | CREATE | Manual trigger endpoint POST /run/{job_id} |
| `api/routers/__init__.py` | MODIFY | Export scheduler_router |
| `api/main.py` | MODIFY | Import scheduler_router, extend WRITE_PATHS, include router |
| `tests/unit/test_scheduler_jobs.py` | CREATE | 11 unit tests for scheduler config and runner |
| `tests/integration/test_scheduler_trigger.py` | CREATE | 5 integration tests for trigger endpoint lifecycle |

## Success Criteria

- [x] `scheduler.add_job` uses `CronTrigger.from_crontab(settings.refresh_cron, timezone="Asia/Bangkok")`
- [x] `misfire_grace_time=3600`, `coalesce=True`, `max_instances=1` are set
- [x] `daily_refresh` writes `results/.tmp/last_refresh.json` on success with `timestamp`, `symbols_fetched`, `duration_seconds`, `failures`
- [x] `daily_refresh` failures logged at ERROR with structured fields; scheduler stays alive
- [x] `POST /api/v1/scheduler/run/daily_refresh` returns 200 with `{job_id, status: "accepted"}`
- [x] Invalid `job_id` returns 400
- [x] Public mode returns 403 via WRITE_PATHS middleware
- [x] Manual trigger submits via JobRegistry, not by calling the scheduler directly
- [x] `create_scheduler(public_mode=True)` returns `None`
- [x] 11 unit tests pass
- [x] 5 integration tests pass
- [x] `uv run ruff check .` exits 0
- [x] `uv run mypy api/` exits 0
- [x] `uv run pytest tests/ -v` — 611 passed, 0 failed (zero regressions from 595)

## Completion Notes

Phase 5.5 implementation was straightforward with no significant issues. The key refactoring — making `daily_refresh` return `dict[str, Any]` — was the right choice: it reduces duplication and ensures the same data pipeline runs whether triggered by cron or manually.

The marker file is written atomically using the same temp-file + rename pattern as `JobRegistry._persist`, ensuring no partial writes in case of a crash mid-write.

The APScheduler `misfire_grace_time=3600` (1 hour) means if the server is down at the scheduled time and comes back within an hour, the missed run will still fire. `coalesce=True` ensures that if multiple misfires accumulate, only one run executes. `max_instances=1` prevents overlapping runs.

### Issues Encountered

1. **Integration test marker file assertions hardcoded to wrong symbol count.** The `private_store` fixture creates 3 universe symbols, but the initial mock only returned OHLCV data for 1. Fixed by returning data for all 3 symbols and adjusting expected counts.

2. **`MockPipeline` unused variables flagged by ruff.** The `FeaturePipeline` mock was being bound to a variable but never used. Fixed by removing the `as MockPipeline` binding (using bare `patch(...)` which still applies the mock).

---

**Document Version:** 1.0
**Author:** Claude Code (Phase 5.5 implementation)
**Status:** Complete
**Completed:** 2026-04-30
