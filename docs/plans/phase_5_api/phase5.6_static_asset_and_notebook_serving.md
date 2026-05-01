# Phase 5.6: Static Asset & Notebook Serving

**Feature:** Production-grade static file and notebook serving for the CSM-SET API
**Branch:** `feature/phase-5-api`
**Created:** 2026-04-30
**Status:** Complete
**Completed:** 2026-04-30
**Depends On:** Phase 5.5 (Complete)

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

Phase 5.6 hardens the static file serving for pre-rendered notebook HTML files and adds a
programmatic `GET /api/v1/notebooks` API endpoint. The existing bare `StaticFiles` mount
at `/static/notebooks/` served HTML files without caching headers or a 404 fallback page.
The `NotebookEntry` and `NotebookIndex` schemas existed as stubs from Phase 5.2 but were
not wired to a router.

### Key Deliverables

1. **`api/static_files.py`** — `NotebookStaticFiles` subclass adding `Cache-Control: public, max-age=300` and a friendly 404 fallback page
2. **`api/static/notebook_missing.html`** — Minimal HTML fallback page returned on 404
3. **`api/routers/notebooks.py`** — `GET /api/v1/notebooks` returning `NotebookIndex` with ETag support
4. **Tests** — 8 unit tests + 13 integration tests (21 total new tests)
5. **Updated wiring** — `api/routers/__init__.py` and `api/main.py` register the new router and use `NotebookStaticFiles`

---

## AI Prompt

The following prompt was used to generate this phase:

```
🎯 Objective
Design and implement Phase 5.6 — Static Asset & Notebook Serving for the csm-set FastAPI project...

📋 Context
- Project: csm-set (FastAPI REST API for SET Cross-Sectional Momentum Strategy)
- Previous phase (5.5): Scheduler production wiring, marker file, manual trigger endpoint
- Current branch: feature/phase-5-api
- Standards: .claude/knowledge/project-skill.md, .claude/playbooks/feature-development.md

🔧 Requirements
- Implement static file serving for assets (/static/*) and Jupyter notebook rendering (/notebooks/*)
- Ensure secure, read-only serving of notebooks and assets (no code execution, no directory traversal)
- Add FastAPI routes for static and notebook endpoints, with proper MIME types and caching headers
- Add tests for static asset and notebook serving (unit and integration)
```

---

## Scope

### In Scope

| Component | Description | Status |
|---|---|---|
| `NotebookStaticFiles` | Custom `StaticFiles` subclass with Cache-Control + 404 fallback | Complete |
| `api/static/notebook_missing.html` | Fallback HTML page for missing notebooks | Complete |
| `GET /api/v1/notebooks` | Notebook index endpoint returning `NotebookIndex` | Complete |
| ETag support | ETag + 304 Not Modified for the index endpoint | Complete |
| `Cache-Control: public, max-age=300` | Caching headers on all static file responses | Complete |
| Path traversal protection | Dynamic directory resolution + `os.path.realpath` checks | Complete |
| Router wiring | `notebooks_router` registered in `api/routers/__init__.py` and `api/main.py` | Complete |
| Unit tests | 8 tests for `NotebookStaticFiles` (construction, headers, fallback) | Complete |
| Integration tests | 13 tests covering index API, ETag, and static file serving | Complete |

### Out of Scope

- On-the-fly `.ipynb` rendering (notebooks are pre-rendered to HTML by the export pipeline)
- General `/static/*` for non-notebook assets (no such assets exist in the project)
- Directory index / browsing UI (the API returns JSON metadata; UI is Phase 6+)

---

## Design Decisions

### 1. Subclass `StaticFiles` rather than ASGI middleware

Cache-Control is notebook-specific. Middleware would check path prefixes on every request. The 404
fallback is naturally handled within the sub-app lifecycle.

### 2. Dynamic directory resolution via `lookup_path` override

`NotebookStaticFiles` overrides `lookup_path()` to resolve the served directory from
`sys.modules["csm.config.settings"].settings.results_dir / "notebooks"` on every request. This
ensures test-level settings patches are honoured, avoiding the import-time binding issue that
would otherwise cause the mount to serve from a stale directory in multi-test suites.

When an explicit `directory` is passed to the constructor (e.g., in unit tests), that fixed path
is used instead.

### 3. `_settings()` helper in the notebook router

The router reads settings through `sys.modules["csm.config.settings"].settings` rather than
using a module-level `from csm.config.settings import settings` binding. This mirrors the
approach used by the `client` test fixture and ensures the router always reads the current
settings, even across test fixtures that repatch the settings module.

### 4. No on-the-fly `.ipynb` rendering

nbconvert is already a dependency, but pre-rendered HTML avoids latency, code execution risk,
and Jupyter kernel dependency at serve time. Notebooks are pre-rendered to HTML by the export
pipeline (`scripts/export_results.py`).

### 5. ETag strategy

The index API ETag is computed from a SHA-256 hash of sorted `name:size_bytes:last_modified`
metadata. Matching the existing patterns in `signals.py` and `portfolio.py`, it uses the
`W/"..."` weak validator format.

---

## Implementation Steps

### Step 1: `api/static/notebook_missing.html`

Created a minimal, self-contained HTML fallback page with a link to browse available notebooks.

### Step 2: `api/static_files.py`

Implemented `NotebookStaticFiles(StaticFiles)` with:
- Constructor accepting optional `directory` and `fallback_path` keyword arguments
- `lookup_path()` override with dynamic directory resolution from current settings
- `file_response()` override adding `Cache-Control: public, max-age=300`
- `get_response()` override catching 404 `HTTPException` and serving the fallback HTML

### Step 3: `api/routers/notebooks.py`

Implemented `GET /api/v1/notebooks` with:
- `_settings()` helper reading settings from `sys.modules`
- `_compute_index_etag()` for content-based weak ETag
- `_problem_response()` helper (matching existing router conventions)
- Handler that scans `settings.results_dir / "notebooks"` for `*.html` files
- Path traversal defence via `Path.resolve()` + `relative_to()` check
- 304 Not Modified short-circuit on ETag match
- Empty directory returns `{"items": []}` (200, not 404)

### Step 4: Router wiring

- `api/routers/__init__.py`: Added `notebooks_router` export
- `api/main.py`: Replaced `StaticFiles` with `NotebookStaticFiles()`, registered `notebooks_router`

### Step 5: Tests

- **Unit tests** (`tests/unit/test_api_static_files.py`): 8 tests covering Cache-Control on 200 and 304, fallback HTML on 404, graceful degradation when fallback is missing, and configurable fallback path
- **Integration fixture** (`tests/integration/conftest.py`): `tmp_results_notebooks_full` writes two sample HTML files
- **Integration tests** (`tests/integration/test_api_notebooks.py`): 13 tests covering index API (schema validation, empty directory, non-HTML filtering), ETag round-trip, and static file serving (Cache-Control, fallback, 304)

---

## File Changes

| File | Action | Description |
|---|---|---|
| `api/static_files.py` | CREATE | `NotebookStaticFiles` subclass with Cache-Control + 404 fallback |
| `api/static/notebook_missing.html` | CREATE | Minimal HTML fallback page |
| `api/routers/notebooks.py` | CREATE | `GET /api/v1/notebooks` endpoint |
| `api/main.py` | MODIFY | Replace `StaticFiles` with `NotebookStaticFiles`, register notebooks router |
| `api/routers/__init__.py` | MODIFY | Export `notebooks_router` |
| `tests/unit/test_api_static_files.py` | CREATE | Unit tests for `NotebookStaticFiles` |
| `tests/integration/test_api_notebooks.py` | CREATE | Integration tests for index + static serving |
| `tests/integration/conftest.py` | MODIFY | Add `tmp_results_notebooks_full` fixture |
| `docs/plans/phase5_api/phase5.6_static_asset_and_notebook_serving.md` | CREATE | This plan document |
| `docs/plans/phase5_api/PLAN.md` | MODIFY | Mark Phase 5.6 complete |

### Files NOT Changed

- `api/schemas/notebooks.py` — Already complete with `NotebookEntry` and `NotebookIndex`
- `api/schemas/__init__.py` — Already exports notebook schemas
- `tests/unit/test_api_schemas.py` — Notebook schema tests already written and passing
- `csm/config/settings.py` — No new settings needed
- `tests/conftest.py` — Existing fixtures already create `results/notebooks/` dir

---

## Success Criteria

- [x] `GET /api/v1/notebooks` returns `NotebookIndex` with correct entry metadata
- [x] Notebook index returns `{"items": []}` when directory is empty (200, not 404)
- [x] ETag header present on notebook index; 304 on `If-None-Match` match
- [x] Static files served with `Cache-Control: public, max-age=300`
- [x] Missing notebook returns 404 with fallback HTML (not plain text)
- [x] Fallback response also includes `Cache-Control` header
- [x] Path traversal protected (both by `NotebookStaticFiles.lookup_path` and router `relative_to` check)
- [x] Non-HTML files in notebooks directory excluded from index
- [x] `uv run ruff check` exits 0 on all new and modified files
- [x] `uv run ruff format --check` exits 0 on all new and modified files
- [x] `uv run mypy api/static_files.py api/routers/notebooks.py` exits 0
- [x] Full test suite: 632 passed, 0 failed (21 new tests, zero regressions)

---

## Completion Notes

### Summary

Phase 5.6 complete. The `NotebookStaticFiles` subclass adds Cache-Control headers and a friendly
404 fallback page to the existing static file serving. The new `GET /api/v1/notebooks` endpoint
provides a programmatic JSON index of available notebook HTML files with ETag-based caching.

### Issues Encountered

1. **Module caching in test fixtures** — The `client` fixture patches `sys.modules["csm.config.settings"].settings` but does not update local `settings` bindings in already-imported router modules. Resolved by using `sys.modules`-based settings access in both the notebook router (`_settings()` helper) and `NotebookStaticFiles` (`lookup_path()` override with dynamic directory resolution).

2. **mypy strict mode** — The `sys.modules` access pattern required explicit `type: ignore[attr-defined]` on dynamic attribute access. The `_settings()` helper needed an `Any` return type (with `# noqa: ANN401` for ruff) because the Settings type is not importable at module level without creating a circular dependency risk.
