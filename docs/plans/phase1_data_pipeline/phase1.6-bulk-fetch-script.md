# Phase 1.6 — Bulk Fetch Script

**Feature:** Data Pipeline — Bulk Fetch Script
**Branch:** `feature/phase-1-data-pipeline`
**Created:** 2026-04-22
**Status:** Complete
**Completed:** 2026-04-22
**Depends On:** Phase 1.5 — Price Cleaner (Complete)

> **Document type:** Combined plan + implementation report. Written before coding
> (plan sections), then updated after coding (completion notes, checked criteria).

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Gap Analysis](#gap-analysis)
5. [Design Decisions](#design-decisions)
6. [CLI Contract](#cli-contract)
7. [Failures File Schema](#failures-file-schema)
8. [Settings Contract](#settings-contract)
9. [Implementation Steps](#implementation-steps)
10. [Verification Addendum](#verification-addendum)
11. [File Changes](#file-changes)
12. [Success Criteria](#success-criteria)
13. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 1.6 delivers `scripts/fetch_history.py` — the single, idempotent entry point that pulls 20
years of daily OHLCV history for every symbol in `data/universe/symbols.json` and writes raw
parquet files to `data/raw/`. It is the bridge between the tvkit loader (Phase 1.3) and the
downstream cleaning and universe-building steps (Phases 1.4–1.5). A second run of the script
must produce zero new fetches; failure at any point must not corrupt already-written data.

### Parent Plan Reference

- `docs/plans/phase1_data_pipeline/PLAN.md` — Phase 1.6 section

### Key Deliverables

1. **`scripts/fetch_history.py`** — rewritten from skeleton to full Phase 1.6 spec:
   reads and Pydantic-validates `symbols.json`, skips already-stored symbols, fetches remaining
   symbols via `OHLCVLoader.fetch_batch()`, saves each to `ParquetStore`, manages
   `<data-dir>/raw/fetch_failures.json` (written on failure with timestamp, deleted on success),
   and exits non-zero if failure rate exceeds the threshold.
2. **`tests/unit/scripts/test_fetch_history.py`** — unit tests covering idempotency,
   failure-rate exit, failures file lifecycle, public-mode guard, and malformed `symbols.json`.

---

## AI Prompt

The following prompt was used to initiate this implementation phase:

```text
🎯 Objective
Create a comprehensive implementation plan and execution workflow for Phase 1.6 — Bulk Fetch
Script in the CSM-SET project, following a plan-before-code methodology. The plan should be
documented in `docs/plans/phase1_data_pipeline/phase1.6-bulk-fetch-script.md` (including the
prompt), and all implementation, documentation, and progress tracking should strictly follow the
referenced project standards and previous phase conventions.

📋 Context
- The CSM-SET project is a cross-sectional momentum strategy system for the SET market.
- The current workflow mandates a rigorous plan-before-code approach, with each phase documented
  in the `docs/plans/phase1_data_pipeline/` directory.
- The previous phase (Phase 1.5 — Price Cleaner) is fully documented in
  `docs/plans/phase1_data_pipeline/phase1.5-price-cleaner.md` and serves as a reference for
  documentation structure, planning, and completion tracking.
- The next phase to implement is Phase 1.6 — Bulk Fetch Script, as described in
  `docs/plans/phase1_data_pipeline/PLAN.md`.
- All progress, issues, and completion notes must be tracked in both the phase-specific markdown
  and the master PLAN.md.

🔧 Requirements
- Carefully read and understand both `docs/plans/phase1_data_pipeline/PLAN.md` (focus on
  Phase 1.6 — Bulk Fetch Script) and `docs/plans/phase1_data_pipeline/phase1.5-price-cleaner.md`
  (for documentation and workflow reference).
- Before coding, create a detailed plan for Phase 1.6 in
  `docs/plans/phase1_data_pipeline/phase1.6-bulk-fetch-script.md`, including:
  - Overview, scope, gap analysis, design decisions, implementation steps, verification, file
    changes, success criteria, and completion notes sections.
  - The full prompt used for this phase, following the format in
    `docs/plans/examples/phase1-sample.md`.
- Only begin implementation after the plan is complete and documented.
- During and after implementation, update both `docs/plans/phase1_data_pipeline/PLAN.md` and
  `docs/plans/phase1_data_pipeline/phase1.6-bulk-fetch-script.md` with progress notes,
  completion checkmarks, issues encountered, and completion dates.
- Ensure all code and documentation strictly follow project architectural principles: type safety,
  async/await for I/O, Pydantic validation, comprehensive error handling, and full test coverage.
- When the phase is complete, commit all changes (including updated docs and code).

📁 Code Context
- `docs/plans/phase1_data_pipeline/PLAN.md` (master plan, phase status, and requirements)
- `docs/plans/phase1_data_pipeline/phase1.5-price-cleaner.md` (last completed phase)
- `docs/plans/examples/phase1-sample.md` (format reference for plan and prompt inclusion)
- Target plan file: `docs/plans/phase1_data_pipeline/phase1.6-bulk-fetch-script.md`
- All relevant code and test files to be created or modified as specified in the plan

✅ Expected Output
- A new plan markdown file at `docs/plans/phase1_data_pipeline/phase1.6-bulk-fetch-script.md`.
- Implementation of the Bulk Fetch Script and all related code/tests as specified in the plan.
- Updated `docs/plans/phase1_data_pipeline/PLAN.md` and
  `docs/plans/phase1_data_pipeline/phase1.6-bulk-fetch-script.md` with progress notes,
  checkmarks, completion dates, and any issues encountered.
- All changes committed upon completion of the phase.
```

---

## Scope

### In Scope (Phase 1.6)

| Component | Description | Status |
| --- | --- | --- |
| `scripts/fetch_history.py` — symbol list loading | Read and Pydantic-validate `<data-dir>/universe/symbols.json`; exit 1 if missing, malformed, or empty | Complete |
| `scripts/fetch_history.py` — idempotency | Skip symbols already present in `<data-dir>/raw/` via `store.exists(symbol)` | Complete |
| `scripts/fetch_history.py` — batch fetch | `OHLCVLoader.fetch_batch()` with concurrency from `Settings` | Complete |
| `scripts/fetch_history.py` — persistence | `ParquetStore.save(symbol, df)` for each success; `StoreError` treated as failure | Complete |
| `scripts/fetch_history.py` — progress logging | `INFO` log: total / skipped / fetched / failed counts | Complete |
| `scripts/fetch_history.py` — failure file | Write `<data-dir>/raw/fetch_failures.json` on failure (with timestamp); delete it on success | Complete |
| `scripts/fetch_history.py` — failure threshold | `sys.exit(1)` if failure rate > `--failure-threshold` (default 0.10) | Complete |
| `scripts/fetch_history.py` — public mode guard | Log error and `sys.exit(1)` if `public_mode=True` | Complete |
| `scripts/fetch_history.py` — CLI validation | `--bars > 0`; `0.0 ≤ --failure-threshold ≤ 1.0` enforced at parse time | Complete |
| `tests/unit/scripts/test_fetch_history.py` | 8 unit tests: idempotency, saves, failures file lifecycle, threshold, public mode, malformed JSON | Complete |

### Out of Scope (Phase 1.6)

- Data Quality Notebook — Phase 1.7
- Incremental / delta fetching (future enhancement — Phase 5)
- Applying `PriceCleaner` — cleaning is a separate, explicit step
- Running `build_universe.py` — the two scripts are independent entry points

---

## Gap Analysis

`scripts/fetch_history.py` already exists as a skeleton committed during Phase 1.3. This section
records the delta between that skeleton and the full Phase 1.6 specification.

### `fetch_history.py` gaps

| Item | Existing skeleton | Required by Phase 1.6 | Action |
| --- | --- | --- | --- |
| Symbol source | Hard-coded list of 5 symbols | Read and Pydantic-validate `<data-dir>/universe/symbols.json` | Rewrite |
| Store key format | `symbol.replace(":", "_")` | `symbol` directly (`ParquetStore` handles encoding via `urllib.parse.quote`) | Fix |
| Idempotency check | `store.exists(symbol.replace(":", "_"))` | `store.exists(symbol)` | Fix |
| Batch size | `bars=3000` | `bars=5040` (~20 years × 252 trading days) | Update |
| Failure tracking | None | Count failures; manage `<data-dir>/raw/fetch_failures.json` | Add |
| Exit on high failure | None | `sys.exit(1)` if failure rate > threshold | Add |
| CLI argument | None | `--data-dir`, `--failure-threshold`, `--bars` with validation | Add |
| Progress logging | Single summary line | Structured log at each stage | Improve |
| Public mode handling | `raise RuntimeError` inline | `logger.error(…); sys.exit(1)` | Standardise |

### Test gaps

| Item | Existing | Required by Phase 1.6 | Action |
| --- | --- | --- | --- |
| Idempotency test | None | Skip already-stored symbols; `fetch_batch` called only for pending symbols | Add |
| Saves test | None | Assert `store.save` called for each successfully fetched symbol | Add |
| Failure threshold exit test | None | Mock partial failure > 10%; assert `SystemExit(1)` | Add |
| Low failure rate test | None | Failure rate ≤ threshold; assert no `SystemExit` | Add |
| Failures file lifecycle test | None | One failure → file written; zero failures → file deleted | Add |
| Public mode test | None | Assert `sys.exit(1)` before any fetch | Add |
| Missing symbols.json test | None | Assert `SystemExit(1)` | Add |
| Malformed symbols.json test | None | Assert `SystemExit(1)` on invalid JSON / wrong structure (including non-list, non-str elements) | Add |

---

## Design Decisions

### 1. Store key is the raw symbol string

`ParquetStore` uses `urllib.parse.quote(key, safe="/")` internally to produce safe filenames.
The correct key for `SET:AOT` is `"SET:AOT"` — callers must not pre-encode or mangle the key.
The skeleton used `symbol.replace(":", "_")` which bypasses the store's encoding contract and
would produce files that `store.exists("SET:AOT")` cannot find. This is corrected in the rewrite.

### 2. `bars=5040` for ~20 years of daily data

252 trading days × 20 years = 5 040 bars. This matches the plan's "20-year pull" wording.
Exposed as a `--bars` CLI argument (default 5040) so it can be overridden in testing or
for partial refreshes without code changes.

### 3. Failure threshold as a CLI argument

The plan says "failure rate > 10% (configurable)". The threshold is exposed as
`--failure-threshold FLOAT` (default `0.10`). This allows CI or manual runs to tighten or
loosen the threshold without modifying the script.

### 4. `<data-dir>/raw/fetch_failures.json` lifecycle and schema

The failures file has a single, consistent lifecycle rule per run:

- **Failures > 0:** write (overwrite) `<data-dir>/raw/fetch_failures.json` with:

  ```json
  {
    "run_timestamp": "2026-04-22T10:00:00+00:00",
    "failed_symbols": ["SET:AAA", "SET:BBB"],
    "count": 2
  }
  ```

- **Failures = 0:** delete `<data-dir>/raw/fetch_failures.json` if it exists.

This means the file is always an accurate reflection of the most recent run. A stale file
from a previous failed run is removed when the follow-up run succeeds. The `run_timestamp`
is an ISO-8601 UTC string generated at the start of `main()`.

### 5. Pydantic validation for `symbols.json`

A private `_SymbolsFile(BaseModel)` validates the loaded JSON strictly:

```python
class _SymbolsFile(BaseModel):
    symbols: list[str]
```

This rejects:

- `{"symbols": "SET:AOT"}` — string, not a list
- `{"symbols": [123, "SET:PTT"]}` — list of non-strings
- `{}` — missing key (Pydantic `ValidationError`)
- `{"symbols": []}` — empty list (checked after validation, exits with code 1)

Using Pydantic here is consistent with the project's "Pydantic for all validated boundaries"
principle and ensures type-safe access to `parsed.symbols`.

### 6. CLI argument validation at parse time

argparse type-converter functions enforce:

- `--bars`: must be > 0 (raises `ArgumentTypeError` otherwise)
- `--failure-threshold`: must be in `[0.0, 1.0]` (raises `ArgumentTypeError` otherwise)

Invalid values produce a standard argparse error message and exit 2 before `main()` runs.

### 7. Empty `symbols.json` is a hard error (exit 1)

A `symbols.json` with `"symbols": []` means either `build_universe.py` was not run yet or
the SET API returned no symbols. Proceeding with an empty list would silently produce a data
directory that appears complete but is actually empty. The script exits with code 1 and an
explicit error message.

### 8. `fetch_batch` called once with all pending symbols

Rather than chunking symbols into multiple `fetch_batch` calls, the script passes all pending
symbols to a single `fetch_batch()` call. `OHLCVLoader.fetch_batch()` already handles
concurrency internally via its semaphore.

### 9. `symbols.json` must exist before `fetch_history.py` runs

`<data-dir>/universe/symbols.json` must be produced by `build_universe.py` (Phase 1.4) before
running the fetch. If the file is missing, contains invalid JSON, fails Pydantic validation,
or contains an empty list, the script logs the error and exits with code 1.

### 10. Public mode exits with code 1, not `RuntimeError`

The skeleton used `raise RuntimeError`. For a CLI entry point, the correct pattern is to log
the error and call `sys.exit(1)` — consistent with how `build_universe.py` handles public mode.

### 11. `StoreError` on save is treated as a fetch failure

`ParquetStore.save()` writes directly to the final path (no tmp+rename atomicity guarantee).
If the process is killed mid-write, a partial parquet file can be left behind that satisfies
`store.exists()` but cannot be read by pyarrow. To handle this:

- `save()` is wrapped in `try/except StoreError`. On error, the script logs the failure and
  counts the symbol as failed.
- If a corrupt file exists from a previous interrupted run, the user can manually delete it;
  re-running will then refetch that symbol. Automatic recovery is out of scope for Phase 1.6.

### 12. Synchronous file I/O inside async `main` — approved exception

`ParquetStore.save()`, `ParquetStore.exists()`, `Path.read_text`, `Path.write_text`, and
`Path.unlink` are all synchronous. Within async `main`, they are called directly without
`asyncio.to_thread`. This is an approved exception, consistent with the documented rationale
in `store.py` and with the existing `build_universe.py` script which calls `_save_symbols_json`
(sync write) directly in its async main:

- These are local, CPU- and memory-bound operations — not network I/O that benefits from
  `asyncio`.
- All blocking calls happen either before `fetch_batch` starts (setup) or after it returns
  (teardown); the event loop has no concurrent tasks to block during these windows.
- This pattern is already established in `build_universe.py`; using `asyncio.to_thread` only
  in `fetch_history.py` would create inconsistency without benefit.

### 13. Division-by-zero guard when all symbols are already cached

When all symbols are already in the store, `pending` is an empty list. The failure-rate check
only executes when `len(pending) > 0`.

### 14. `Settings` instantiated directly, not via `get_settings()`

`build_universe.py` instantiates `Settings()` directly. `fetch_history.py` follows the same
pattern for consistency across scripts.

---

## CLI Contract

```text
usage: fetch_history.py [-h] [--data-dir PATH] [--bars N] [--failure-threshold F]

Fetch 20-year daily OHLCV history for all SET universe symbols.

options:
  --data-dir PATH         Root data directory (default: Settings.data_dir)
  --bars N                Bars per symbol; must be > 0 (default: 5040, ~20 years × 252)
  --failure-threshold F   Max allowed failure rate [0.0, 1.0] before non-zero exit (default: 0.10)
```

**Exit codes:**

| Code | Meaning |
| --- | --- |
| 0 | All symbols fetched (or already cached); failure rate ≤ threshold |
| 1 | `symbols.json` missing/malformed/invalid/empty; public mode active; or failure rate > threshold |
| 2 | Invalid CLI argument (argparse error) |

---

## Failures File Schema

`<data-dir>/raw/fetch_failures.json` — written when any symbol fails; deleted when zero failures:

```json
{
  "run_timestamp": "2026-04-22T10:00:00+00:00",
  "failed_symbols": ["SET:AAA", "SET:BBB"],
  "count": 2
}
```

| Field | Type | Description |
| --- | --- | --- |
| `run_timestamp` | ISO-8601 UTC string | Start time of the run that produced this file |
| `failed_symbols` | list[str] | Symbols that failed fetch or save |
| `count` | int | Length of `failed_symbols` |

---

## Settings Contract

`fetch_history.py` reads the following from `Settings`:

| Setting | Source | Used for |
| --- | --- | --- |
| `public_mode` | `CSM_PUBLIC_MODE` env var | Early exit guard |
| `log_level` | `CSM_LOG_LEVEL` env var | `logging.basicConfig` level |
| `data_dir` | `CSM_DATA_DIR` env var | Default base path (overridden by `--data-dir`) |
| `tvkit_concurrency` | `CSM_TVKIT_CONCURRENCY` env var | Passed to `OHLCVLoader` |
| `tvkit_retry_attempts` | `CSM_TVKIT_RETRY_ATTEMPTS` env var | Passed to `OHLCVLoader` |

---

## Implementation Steps

### Step 1: Write this plan document (complete before any code changes) ✓

### Step 2: Rewrite `scripts/fetch_history.py`

1. Add `_SymbolsFile(BaseModel)` private Pydantic model with `symbols: list[str]`
2. Add `_positive_int(value: str) -> int` argparse type for `--bars` (raises `ArgumentTypeError` if ≤ 0)
3. Add `_unit_float(value: str) -> float` argparse type for `--failure-threshold` (raises if outside `[0.0, 1.0]`)
4. Add `_parse_args()` using the type validators above
5. Add `_load_symbols(path: Path) -> list[str]` — reads `symbols.json`, Pydantic-validates,
   checks for empty list; calls `sys.exit(1)` on any error
6. Rewrite `main()`:
   - Capture `run_timestamp = datetime.now(timezone.utc)` at start
   - Instantiate `Settings()` and check `public_mode` → log + `sys.exit(1)`
   - Resolve `data_dir` from arg or `settings.data_dir`
   - Instantiate `ParquetStore(data_dir / "raw")` and `OHLCVLoader(settings)`
   - Load symbols via `_load_symbols(data_dir / "universe" / "symbols.json")`
   - Compute `pending = [s for s in symbols if not store.exists(s)]`
   - Log: `Found N symbols; skipping M already fetched; fetching P`
   - Await `loader.fetch_batch(pending, "1D", bars)`
   - For each result, call `store.save(symbol, df)` in `try/except StoreError`
   - Collect `failed = [s for s in pending if s not in successfully_saved]`
   - If `len(failed) > 0`: write `<data-dir>/raw/fetch_failures.json` (with `run_timestamp`, `failed_symbols`, `count`)
   - Else: delete `<data-dir>/raw/fetch_failures.json` if it exists
   - Log final counts
   - If `len(pending) > 0` and `len(failed) / len(pending) > threshold`: `sys.exit(1)`

### Step 3: Create `tests/unit/scripts/__init__.py` and `tests/unit/scripts/test_fetch_history.py`

| # | Test name | What it verifies |
| --- | --- | --- |
| 1 | `test_skips_already_stored_symbols` | `store.exists` True for N symbols; `fetch_batch` called with remaining symbols only |
| 2 | `test_saves_fetched_symbols_to_store` | Successful fetch → `store.save` called for each symbol with the raw symbol string as key |
| 3 | `test_writes_fetch_failures_json_on_failure` | One symbol fails; `fetch_failures.json` written with correct schema including `run_timestamp` |
| 4 | `test_deletes_fetch_failures_json_on_success` | Zero failures → `fetch_failures.json` deleted if it existed |
| 5 | `test_exits_nonzero_on_high_failure_rate` | Failure rate > threshold → `SystemExit(1)` |
| 6 | `test_public_mode_exits_before_fetch` | `public_mode=True` → `SystemExit(1)`; `fetch_batch` never called |
| 7 | `test_exits_if_symbols_json_missing` | `symbols.json` absent → `SystemExit(1)` |
| 8 | `test_exits_if_symbols_json_malformed` | Invalid JSON, non-list `symbols`, non-str elements, or empty list → `SystemExit(1)` |

### Step 4: Run verification suite (see below)

### Step 5: Update PLAN.md and this document; commit

---

## Verification Addendum

Run in this exact order:

```bash
# Focused script tests
uv run python -m pytest tests/unit/scripts/test_fetch_history.py -v   # must: 8 passed

# Type check
uv run mypy scripts/fetch_history.py   # must: exit 0

# Lint and format
uv run ruff check scripts/fetch_history.py           # must: exit 0
uv run ruff format --check scripts/fetch_history.py  # must: exit 0

# Full Phase 1 unit suite — confirm no regressions in new or changed code
uv run python -m pytest tests/unit/config/ tests/unit/data/ tests/unit/scripts/ -v
# All tests must pass.
```

Note: `test_regime_transitions_on_known_price_series` in `tests/unit/risk/` is a pre-existing
failure unrelated to Phase 1.6 and is excluded from scope by the directory-scoped run above.

---

## File Changes

| File | Action | Description |
| --- | --- | --- |
| `scripts/fetch_history.py` | MODIFY | Rewrite skeleton to full Phase 1.6 spec |
| `tests/unit/scripts/__init__.py` | CREATE | Package marker |
| `tests/unit/scripts/test_fetch_history.py` | CREATE | 8 unit tests |
| `docs/plans/phase1_data_pipeline/phase1.6-bulk-fetch-script.md` | CREATE | This document |
| `docs/plans/phase1_data_pipeline/PLAN.md` | MODIFY | Phase 1.6 status + completion notes |

---

## Success Criteria

- [x] `scripts/fetch_history.py` reads and Pydantic-validates symbol list from `<data-dir>/universe/symbols.json`
- [x] Script exits with code 1 on missing, malformed (including non-list / non-str elements), or empty `symbols.json`
- [x] `--bars` must be > 0; `--failure-threshold` must be in `[0.0, 1.0]` (argparse type validation)
- [x] Script skips symbols already present in `<data-dir>/raw/` (idempotent)
- [x] Script uses `symbol` directly as `ParquetStore` key (not `symbol.replace(":", "_")`)
- [x] `fetch_batch` called once with all pending symbols; concurrency from `Settings`
- [x] `StoreError` on `save()` treated as a per-symbol failure
- [x] `<data-dir>/raw/fetch_failures.json` written (with `run_timestamp`, `failed_symbols`, `count`) on failure; deleted on success
- [x] Script exits with code 1 when failure rate > `--failure-threshold`
- [x] Script exits with code 1 when `CSM_PUBLIC_MODE=true`
- [x] `uv run python -m pytest tests/unit/scripts/test_fetch_history.py -v` — 8 passed
- [x] `uv run mypy scripts/fetch_history.py` exits 0
- [x] `uv run ruff check scripts/fetch_history.py` exits 0
- [x] No regressions in `tests/unit/config/`, `tests/unit/data/`, `tests/unit/scripts/`

---

## Completion Notes

### Summary

Phase 1.6 complete. `scripts/fetch_history.py` rewritten from stub to full spec:
reads and Pydantic-validates `<data-dir>/universe/symbols.json`, skips already-fetched symbols
via `store.exists(symbol)`, calls `fetch_batch()` for all pending symbols, saves each result to
`ParquetStore` (wrapping `StoreError` as a counted failure), manages
`<data-dir>/raw/fetch_failures.json` (written with `run_timestamp` on failure, deleted on
success), and exits non-zero if the failure rate exceeds the configurable threshold. Key encoding
bug (`:` → `_`) in the skeleton corrected. 8 unit tests pass. `mypy` and `ruff` exit 0. No new
regressions.

### Issues Encountered

1. **Key encoding bug in skeleton** — The Phase 1.3 skeleton used `symbol.replace(":", "_")` as
   the `ParquetStore` key, bypassing the store's own `urllib.parse.quote` encoding. Fixed by
   passing `symbol` directly as the key.

2. **Division-by-zero when all symbols cached** — When all symbols are already in the store,
   `pending` is empty. Guard added: failure-rate check only runs when `len(pending) > 0`.

3. **`ParquetStore.save` is not atomic** — The store writes directly to the final path without
   a tmp+rename pattern. A process killed mid-write may leave a corrupt parquet file that
   `store.exists()` finds but pyarrow cannot read. Documented as a known constraint; manual
   deletion of the corrupt file is required before re-running.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Sonnet 4.6)
**Status:** Complete
**Completed:** 2026-04-22
