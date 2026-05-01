# Phase 6.4 — Data Boundary Audit (File + API)

**Feature:** Two-layer data boundary audit — file system scan + API response scan — to guarantee no OHLCV leaks in public distribution
**Branch:** `feature/phase-6-docker`
**Created:** 2026-05-01
**Status:** In Progress
**Depends on:** Phase 6.1 (Multi-stage Dockerfile — complete), Phase 6.2 (Docker Compose — complete), Phase 6.3 (Export Results Script — complete)
**Positioning:** Hardens the public-mode data contract by adding automated checks that fail CI if raw OHLCV fields (open, high, low, close, volume, adj_close) appear in any committed JSON/HTML file or any public-mode API response.

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

Phase 6.4 implements two complementary automated checks so OHLCV leaks are caught at both the filesystem and API layers, regardless of which frontend calls the API. The static-file walk catches owner mistakes at commit time; the API-response walk catches runtime regressions in handler code. Together they form the production guarantee that prevents the project's defining promise — no raw OHLCV in public distribution — from regressing.

### Parent Plan Reference

- `docs/plans/phase_6_docker/PLAN.md` — Phase 6.4 section

### Key Deliverables

1. **`tests/integration/test_public_data_boundary_files.py`** — File system scan for OHLCV leaks in committed JSON/HTML
2. **`tests/integration/test_public_data_boundary_api.py`** — API response scan for OHLCV leaks + write-endpoint 403 assertions
3. **`.gitignore`** — Verify and document data/ and results/ boundary patterns

---

## AI Prompt

The following prompt was used to generate this phase:

```
You are tasked with implementing Phase 6.4 — Data Boundary Audit (File + API) for the csm-set project. Follow these steps precisely:

1. **Preparation**
   - Carefully read `.claude/knowledge/project-skill.md` and `.claude/playbooks/feature-development.md` to internalize all engineering standards and workflow expectations.
   - Review `docs/plans/phase_6_docker/PLAN.md`, focusing on the Phase 6.4 section, and `docs/plans/phase_6_docker/phase_6_3_export_results.md` for context on previous deliverables.

2. **Planning**
   - Draft a detailed implementation plan for Phase 6.4 in markdown, using the format from `docs/plans/examples/phase1-sample.md`.
   - Your plan must include: scope, deliverables, acceptance criteria, risks, and the full AI agent prompt (this prompt).
   - Save the plan as `docs/plans/phase_6_docker/phase_6_4_data_boundary_audit.md`.

3. **Implementation**
   - Only begin coding after the plan is complete and saved.
   - Implement all deliverables for Phase 6.4:
     - Automated file system scan to detect any OHLCV or sensitive data in `results/static/` and related output trees.
     - API response audit to ensure no OHLCV or sensitive fields are exposed via endpoints serving frontend-agnostic data.
     - Add or update tests to cover both file and API boundaries.
     - Document findings, remediation steps, and verification in the plan file.
   - Ensure all code follows project standards: type safety, async/await, Pydantic validation, error handling, and import organization.

4. **Documentation and Progress Tracking**
   - Update `docs/plans/phase_6_docker/PLAN.md` and `docs/plans/phase_6_docker/phase_6_4_data_boundary_audit.md` with progress notes, completion status, and any issues encountered.
   - Mark acceptance criteria as completed or note any deviations.

5. **Commit and Finalization**
   - Commit all changes in a single commit with a clear, standards-compliant message summarizing the work.
   - Ensure all tests pass and the implementation meets the acceptance criteria.

**Files to reference and/or modify:**
- .claude/knowledge/project-skill.md
- .claude/playbooks/feature-development.md
- docs/plans/phase_6_docker/PLAN.md
- docs/plans/phase_6_docker/phase_6_3_export_results.md
- docs/plans/examples/phase1-sample.md
- Output directories: results/static/, results/backtest/, results/signals/, results/notebooks/
- API endpoints serving data from these outputs

**Expected deliverables:**
- A new plan markdown file at `docs/plans/phase_6_docker/phase_6_4_data_boundary_audit.md` with the full implementation plan and embedded prompt.
- All Phase 6.4 deliverables implemented and tested.
- Updated progress/completion notes in both `docs/plans/phase_6_docker/PLAN.md` and the new phase plan file.
- A single commit with all changes and a standards-compliant message.

Begin by drafting the plan markdown file. Do not start implementation until the plan is complete and saved.
```

---

## Scope

### In Scope

| Component | Description | Status |
|---|---|---|
| `tests/integration/test_public_data_boundary_files.py` | File-system walk: scans `results/**/*.json` and `results/**/*.html` for forbidden OHLCV keys and large numeric arrays | Pending |
| `tests/integration/test_public_data_boundary_api.py` | API-response walk: hits public-mode GET endpoints, recursively scans JSON for forbidden keys; asserts write endpoints return 403 | Pending |
| `.gitignore` | Verify existing data/result boundary patterns; add clarifying comments | Pending |
| `docs/plans/phase_6_docker/PLAN.md` | Update Phase 6.4 status + completion notes | Pending |

### Out of Scope

- Modifying API routers to read from `results/static/` instead of `results/` (separate path-migration task)
- Creating `results/static/` directory or running `export_results.py` to populate it
- Modifying the public mode guard middleware
- Phase 6.5 (README rewrite)
- Phase 6.6/6.7 (CI workflows)

---

## Design Decisions

### 1. File audit walks `results/` not just `results/static/`

The PLAN specifies `results/static/**/*.json` as the audit target. However:
- `results/static/` does not exist yet (Phase 6.3 defaults to it but the export hasn't been run)
- The API currently reads from `results/{signals,backtest,notebooks}/` directly
- The committed `results/signals/latest_ranking.json` contains real signal data

**Decision:** Walk `results/**/*.json` and `results/**/*.html` (excluding `results/.tmp/`). This covers both the current API-serving tree and the future `results/static/` tree. The walk skips `.tmp/` since it's gitignored.

### 2. Forbidden key set

Case-insensitive match against: `open`, `high`, `low`, `close`, `volume`, `adj_close`, `adjusted_close`. These are the canonical OHLCV field names used throughout the financial data pipeline.

### 3. Large numeric array heuristic

If any JSON value is a list of > 400 numbers, flag it as a potential price-data leak disguised under a benign key name. 400 is ~1.5 years of daily prices — far more than any summary metric would contain. This heuristic is documented in the PLAN.

### 4. HTML table heuristic

Parse HTML files for `<table>` elements. If a table contains > 5 columns where > 80% of cells are numeric, flag it as a potential raw price table. Rendered notebook charts have 0 such columns; a raw OHLCV dump would have 5+ (Date, Open, High, Low, Close, Volume).

### 5. API audit: test actual endpoints, not aspirational ones

The PLAN lists `/api/v1/backtest/summary`, `/api/v1/backtest/equity_curve`, `/api/v1/portfolio/holdings`, and `/api/v1/portfolio/regime` as endpoints to test — but these do not exist in the current API. The actual API has:

**Read endpoints (test for OHLCV in response):**
- `GET /api/v1/signals/latest`
- `GET /api/v1/portfolio/current`
- `GET /api/v1/universe`
- `GET /api/v1/notebooks`
- `GET /health`

**Write endpoints (assert 403 in public mode):**
- `POST /api/v1/backtest/run`
- `POST /api/v1/data/refresh`
- `POST /api/v1/scheduler/run/daily_refresh`
- `GET /api/v1/jobs`

### 6. Recursive JSON scanner

The scanner recursively walks all dict keys, list items, and nested structures in API responses. When a forbidden key is found, it reports the full JSON path (e.g., `rankings[3].close`) and the HTTP endpoint that returned it.

### 7. Single test file per boundary layer

Keep two separate test files as specified by the PLAN (files + API), matching the existing pattern of `test_cors.py` and `test_export_results.py`. Each file uses the `public_client` fixture from the root `conftest.py`.

### 8. .gitignore: verify, don't rewrite

The current `.gitignore` already has:
- `/data/` — blocks all market data
- `results/.tmp/` — blocks temporary artifacts
- `.env` and `.env.*` — blocks credentials
- `!.env.example` — whitelists the example

These meet the PLAN's requirements. The only addition is a clarifying comment block documenting the data boundary strategy.

---

## Implementation Steps

### Step 1: Create `tests/integration/test_public_data_boundary_files.py`

Implement file-system boundary audit with these components:

1. **`FORBIDDEN_KEYS`** — `frozenset` of lowercase OHLCV field names
2. **`_scan_json_object(obj, path)`** — recursive generator yielding `(json_path, forbidden_key)` tuples for any dict key matching a forbidden key (case-insensitive)
3. **`_check_large_numeric_array(obj, path)`** — checks if any list value has > 400 numeric entries; yields `(json_path, length)` warnings
4. **`_scan_html_file(filepath)`** — parses HTML with `html.parser`, finds `<table>` elements, counts numeric columns; yields `(filepath, table_index, column_count)` for tables with > 5 numeric columns
5. **`test_json_files_no_ohlcv_keys()`** — parametrized test that walks `results/**/*.json` (excluding `.tmp/`), loads each file, and runs `_scan_json_object`. Fails with actionable message like `results/signals/latest_ranking.json: forbidden key 'close' at rankings[3].close`
6. **`test_json_files_no_large_numeric_arrays()`** — parametrized test checking the array heuristic
7. **`test_html_files_no_price_tables()`** — parametrized test checking HTML table heuristic for `results/**/*.html`
8. **`test_results_static_clean_if_exists()`** — conditional test: if `results/static/` exists, runs the same scan on it

### Step 2: Create `tests/integration/test_public_data_boundary_api.py`

Implement API-response boundary audit:

1. **`FORBIDDEN_KEYS`** — same set as file audit
2. **`_scan_response(obj, path)`** — recursive scanner (reuse or duplicate; keep files independent)
3. **`_assert_no_forbidden_keys(response, endpoint)`** — helper that calls `_scan_response` on `response.json()` and raises `AssertionError` with `GET /endpoint → json.path.key`
4. **`READ_ENDPOINTS`** — list of `(method, path)` tuples for public read endpoints
5. **`WRITE_ENDPOINTS`** — list of `(method, path, body)` tuples for write endpoints that must return 403
6. **`test_read_endpoints_no_ohlcv()`** — parametrized: hits each read endpoint via `public_client`, asserts 200, scans response for forbidden keys
7. **`test_write_endpoints_return_403()`** — parametrized: hits each write endpoint, asserts 403 with `"Disabled in public mode"` in body
8. **`test_deliberate_leak_detected()`** — negative test: monkeypatches a response to include a `"close": 1.23` field, verifies the scanner catches it

### Step 3: Update `.gitignore`

Add a comment block documenting the data boundary strategy above the existing `data/` and `results/` sections. No functional changes needed — current patterns already satisfy the PLAN's requirements.

### Step 4: Run quality gate

```bash
uv run ruff check . && uv run ruff format . && uv run mypy src/ && uv run pytest tests/integration/test_public_data_boundary_files.py tests/integration/test_public_data_boundary_api.py -v
```

### Step 5: Update master plan

Mark Phase 6.4 deliverables as complete in `docs/plans/phase_6_docker/PLAN.md`. Add completion notes to this file.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `tests/integration/test_public_data_boundary_files.py` | CREATE | File-system boundary audit (~120 lines) |
| `tests/integration/test_public_data_boundary_api.py` | CREATE | API-response boundary audit (~140 lines) |
| `.gitignore` | MODIFY | Add data boundary comment block |
| `docs/plans/phase_6_docker/PLAN.md` | MODIFY | Update Phase 6.4 status + completion notes |
| `docs/plans/phase_6_docker/phase_6_4_data_boundary_audit.md` | MODIFY | This file — completion notes |

---

## Success Criteria

- [x] `test_public_data_boundary_files.py` passes on the committed `results/` tree (no OHLCV found)
- [x] Adding a deliberate OHLCV leak (e.g., `"close": 1.23` in `results/signals/latest_ranking.json`) makes the file audit fail with the offending path
- [x] `test_public_data_boundary_api.py` passes — all read endpoints return 200 with no OHLCV keys
- [x] All write endpoints return 403 with `"Disabled in public mode"` body
- [x] Adding a deliberate leak in an API handler response makes the API audit fail
- [x] HTML table heuristic correctly identifies a synthetic price table in a fixture HTML file
- [x] Large numeric array heuristic correctly flags a synthetic 500-element array
- [x] `.gitignore` boundary comments are clear and accurate
- [x] Quality gate green: ruff check (changed files), ruff format, mypy (changed files), 27/27 new tests pass
- [x] No regressions in existing test suite

---

## Completion Notes

### Summary

Phase 6.4 complete. Two new boundary audit test files (27 tests total) were created:

- **`tests/integration/test_public_data_boundary_files.py`** (15 tests) — walks `results/**/*.json` and `results/**/*.html`, recursively scans for forbidden OHLCV keys (case-insensitive), flags >400-element numeric arrays as potential raw price series, and detects HTML tables with >4 numeric columns (header row excluded). All 4 committed JSON files and 4 committed HTML files pass. Three deliberate-leak negative tests verify the scanners catch violations.

- **`tests/integration/test_public_data_boundary_api.py`** (12 tests) — boots a public-mode `TestClient`, hits 4 read endpoints (`/api/v1/signals/latest`, `/api/v1/portfolio/current`, `/api/v1/notebooks`, `/health`) and scans responses for OHLCV keys. Verifies 4 write endpoints return 403 with canonical "Disabled in public mode" body. Four scanner/deliberate-leak tests verify detection logic.

- **`.gitignore`** — added a data boundary strategy comment block documenting the three-layer approach. Existing patterns already satisfied all requirements.

### Key implementation details

- **Walk scope broadened:** `results/` instead of `results/static/` (which doesn't exist yet). Covers both the current API-serving tree and future static tree.
- **API endpoints adjusted to reality:** The PLAN listed several endpoints that don't exist (`/api/v1/backtest/summary`, etc.). Audit tests the 4 read + 4 write endpoints that actually exist.
- **HTML threshold adjusted:** From `> 5` to `> 4` numeric columns (threshold=4). A standard OHLCV table has 5 numeric data columns; the header row is now skipped during ratio calculation to prevent column labels from diluting the detection.
- **Recursive scanner:** Both test files contain independent scanner implementations (by design — test file independence). Each walks nested dict/list structures and reports full JSON paths (e.g., `$.rankings[3].close`).

### Issues Encountered

1. **HTML table detection — header row dilution:** The `_TableColumnCounter` was counting header text ("Open", "High", etc.) as non-numeric, diluting the numeric ratio from 100% to 67% per column. Fixed by skipping `self._rows[0]` (header row) in the ratio calculation.
2. **`/api/v1/universe` returns 404 in public test client:** The universe endpoint reads from `ParquetStore` with no public JSON fallback. Removed from `READ_ENDPOINTS` — it's a private-mode-only endpoint.
3. **mypy `**kwargs` variance error:** Passing `**dict[str, object]` to `TestClient.request()` triggers mypy invariance errors on the `json` parameter. Fixed by using an explicit `if/else` branch instead of `**kwargs`.

### Test Results

- **27/27** new tests pass (15 file audit + 12 API audit)
- **ruff check:** clean on changed files (pre-existing notebook warnings unrelated)
- **ruff format:** applied
- **mypy:** clean on changed files
- **Existing test suite:** no regressions (9 pre-existing test isolation failures in `test_export_models.py` unrelated to Phase 6.4)

---

**Document Version:** 1.1
**Author:** AI Agent
**Created:** 2026-05-01
**Status:** Complete
