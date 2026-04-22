# Phase 1.2 — Storage Layer

**Feature:** Data Pipeline — Storage Layer
**Branch:** `feature/phase-1-data-pipeline`
**Created:** 2026-04-22
**Status:** In Progress
**Depends On:** Phase 1.1 — Config & Constants (Complete)

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Gap Analysis](#gap-analysis)
5. [Design Decisions](#design-decisions)
6. [Implementation Steps](#implementation-steps)
7. [Verification Addendum](#verification-addendum)
8. [File Changes](#file-changes)
9. [Success Criteria](#success-criteria)
10. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 1.2 encapsulates all parquet I/O behind a single `ParquetStore` class. After this phase no
caller anywhere in the pipeline touches `pyarrow`, `pd.read_parquet`, or file paths directly.
`ParquetStore` is the single point of truth for where and how pipeline artefacts are persisted.

### Parent Plan Reference

- `docs/plans/phase1_data_pipeline/PLAN.md` — Phase 1.2 section

### Key Deliverables

1. **`src/csm/data/store.py`** — `ParquetStore` with full CRUD: `save / load / exists / list_keys / delete`, key validation, reversible percent-encoding for `:` in filenames.
2. **`tests/unit/data/__init__.py`** — Package marker enabling pytest collection.
3. **`tests/unit/data/test_store.py`** — 8 unit tests covering all public methods and contract edge cases.

---

## AI Prompt

The following prompt was used to initiate this implementation phase:

```text
🎯 Objective
Create a comprehensive implementation plan and execution workflow for Phase 1.2 — Storage Layer of
the Data Pipeline Master Plan, following all architectural, documentation, and workflow standards.
The plan must be saved as a markdown file at
docs/plans/phase1_data_pipeline/phase1.2-storage-layer.md, include the full prompt used, and only
begin implementation after the plan is complete. Upon completion, update all relevant documentation
files with progress notes and commit all changes.

📋 Context
- The project is a type-safe, async-first Python data pipeline for SET OHLCV data, using Pydantic
  for configuration and validation.
- The previous phase (Phase 1.1 — Config & Constants) is complete and documented at
  docs/plans/phase1_data_pipeline/phase1.1-config-and-constants.md.
- The master plan and requirements for Phase 1.2 — Storage Layer are detailed in
  docs/plans/phase1_data_pipeline/PLAN.md.
- All code must follow strict architectural, type safety, async, and documentation standards as
  outlined in the .github/instructions directory.

🔧 Requirements
- Read and understand docs/plans/phase1_data_pipeline/PLAN.md, focusing on Phase 1.2 — Storage
  Layer.
- Review docs/plans/phase1_data_pipeline/phase1.1-config-and-constants.md for context and
  integration points.
- Draft a detailed implementation plan for Phase 1.2 in markdown, saved as
  docs/plans/phase1_data_pipeline/phase1.2-storage-layer.md.
  - The plan must include: objectives, deliverables, step-by-step tasks, anticipated challenges,
    and the exact prompt used (for traceability).
  - Follow the format reference at docs/plans/examples/phase1-sample.md.
- Do not begin coding until the plan is complete and saved.
- After implementation, update both docs/plans/phase1_data_pipeline/PLAN.md and
  docs/plans/phase1_data_pipeline/phase1.2-storage-layer.md with progress notes, completion
  dates, and any issues encountered.
- All code must be type-safe, async-first, use Pydantic for all models/configuration, and include
  comprehensive docstrings and tests.
- Commit all changes with a clear, standards-compliant commit message.

📁 Code Context
- docs/plans/phase1_data_pipeline/PLAN.md (master plan and requirements)
- docs/plans/phase1_data_pipeline/phase1.1-config-and-constants.md (previous phase, integration
  context)
- docs/plans/examples/phase1-sample.md (plan format reference)
- .github/instructions/ (coding, documentation, and workflow standards)

✅ Expected Output
- A new plan file at docs/plans/phase1_data_pipeline/phase1.2-storage-layer.md, following the
  required format and including the full prompt.
- Implementation of Phase 1.2 — Storage Layer, fully type-safe, async, Pydantic-based, and
  tested.
- Updated docs/plans/phase1_data_pipeline/PLAN.md and
  docs/plans/phase1_data_pipeline/phase1.2-storage-layer.md with progress notes and completion
  details.
- All changes committed with a standards-compliant commit message.
```

---

## Scope

### In Scope (Phase 1.2)

| Component | Description | Status |
| --- | --- | --- |
| `store.py` — `__init__(base_dir)` | Accepts data root; creates directory tree if absent | Complete |
| `store.py` — `save(key, df)` | Validates key; encodes `:` → `%3A`; writes parquet; returns `None` | Complete |
| `store.py` — `load(key)` | Validates key; reads parquet; raises `KeyError` if file absent | Complete |
| `store.py` — `exists(key)` | Validates key; returns `True` if parquet file is present | Complete |
| `store.py` — `list_keys()` | Returns sorted canonical keys (percent-decode stems) | Complete |
| `store.py` — `delete(key)` | Validates key; removes parquet; raises `KeyError` if file absent | Complete |
| `store.py` — `_validate_key()` | Rejects empty, whitespace-only, `..` traversal, leading `/` | Complete |
| `store.py` — `_key_to_filename()` / `_filename_to_key()` | Reversible percent-encoding of `:` | Complete |
| `tests/unit/data/__init__.py` | Package marker for pytest collection | Complete |
| `tests/unit/data/test_store.py` | 8 unit tests covering all public methods and contracts | Complete |

### Out of Scope (Phase 1.2)

- tvkit loader (`OHLCVLoader`) and retry logic — Phase 1.3
- Universe builder and dated snapshot keys (`universe/{YYYY-MM-DD}`) — Phase 1.4
- Price cleaner — Phase 1.5
- Bulk fetch script and notebook — Phases 1.6–1.7
- Updating `pipeline.py` / `backtest.py` call sites to the revised signature — those are
  pre-existing stubs; the store's synchronous API is intentional (see Design Decisions §2)

---

## Gap Analysis

`src/csm/data/store.py` already exists with a partial implementation. This section records the
delta between the existing code and the Phase 1.2 plan specification.

### `store.py` gaps

| Item | Existing | Required by Plan | Action |
| --- | --- | --- | --- |
| `save` return type | `Path` | `None` | Remove `return path`; update signature and docstring |
| `save` / `load` / `exists` param name | `name` | `key` | Rename for consistency with plan spec |
| `load` error on missing | raises `StoreError` | raises `KeyError` | Change exception type |
| Key validation | absent | reject empty, traversal, leading `/` | Add `_validate_key()` |
| Key encoding (`:` → filesystem-safe) | absent | reversible percent-encoding | Add `_key_to_filename()` / `_filename_to_key()` |
| `list_keys` reverse-decoding | absent | percent-decode stems | Update `list_keys` |
| `delete` method | absent | raises `KeyError` if missing | Add method |

### Test gaps

| Item | Existing | Required by Plan | Action |
| --- | --- | --- | --- |
| `tests/unit/data/__init__.py` | absent | required for consistent collection | Create |
| `tests/unit/data/test_store.py` | absent | 8 tests | Create |

### Baseline state

```bash
# Recorded before any edits:
git branch --show-current   # feature/phase-1-data-pipeline
git status                  # M .python-version, M README.md (pre-existing)
uv run python -m pytest tests/unit/config/ tests/unit/data/ \
    tests/unit/features/ tests/unit/risk/ -v
# Result: 3 pre-existing failures (test_loader × 2, test_regime × 1); 14 passed
```

The 3 pre-existing failures are unrelated to the storage layer and must not change after this
phase.

---

## Design Decisions

### 1. `save` returns `None`

The plan specifies `save(key, df) -> None`. The internal file path is an implementation detail and
must not leak. Callers that need to verify persistence can call `exists(key)`. No existing call
site uses the returned `Path`, so this is a safe signature tightening.

### 2. `ParquetStore` stays synchronous — project-approved exception

The project instructions require async-first I/O. `ParquetStore` is intentionally synchronous for
the following reasons, recorded here as an explicit architectural exception:

- pyarrow's `read_parquet` / `to_parquet` are CPU-bound, memory-bound operations over local
  files. They release the GIL partially but are not I/O-bound in the network sense that async
  truly benefits.
- `ParquetStore` is called from batch processing scripts (`fetch_history.py`,
  `build_universe.py`) that are themselves synchronous entry points, not from request handlers
  or concurrent coroutines.
- Making `ParquetStore` async would require wrapping every pyarrow call in
  `asyncio.to_thread()` and updating all callers — a non-trivial ripple across
  `pipeline.py`, `backtest.py`, and future phases.
- The async-first rule applies primarily to network I/O (HTTP, WebSocket, database
  connections). Local filesystem parquet I/O is the approved exception.

**If** a future phase requires non-blocking parquet I/O (e.g., concurrent batch fetch in
`OHLCVLoader.fetch_batch`), the recommended pattern is to wrap individual `ParquetStore` calls
with `asyncio.to_thread(store.save, key, df)` at the call site. No change to `ParquetStore`'s
interface is required.

### 3. Key validation

Keys are validated before any path construction. `_validate_key(key)` raises `ValueError` with
a descriptive message for:

- Empty or whitespace-only string — `key.strip() == ""`
- Path traversal: any `/`-split component that is `""`, `"."`, or `".."`

Notably, `/` is **allowed** as a path segment separator. A key like `universe/2024-01-31`
produces the file `{base_dir}/universe/2024-01-31.parquet`, where the `universe/` subdirectory
is created automatically on `save`. This is the intentional design for Phase 1.4 universe
snapshot keys. Only the `..` traversal pattern is rejected.

### 4. Key encoding — reversible percent-encoding for `:`

SET symbol keys have the form `EXCHANGE:TICKER` (e.g. `SET:AOT`). The colon is illegal in
Windows filenames and strongly discouraged on macOS.

**Strategy:** percent-encode `:` as `%3A` in the filename stem. This is:

- Fully reversible: `SET:AOT` → stem `SET%3AAOT` → key `SET:AOT`
- Unambiguous: `%3A` is a three-character sequence that cannot be confused with any valid key
  character
- Future-safe: if additional special characters need encoding (e.g. `?`, `*`, `<`), the same
  scheme extends naturally

```python
def _key_to_filename(key: str) -> str:
    return key.replace(":", "%3A")

def _filename_to_key(stem: str) -> str:
    return stem.replace("%3A", ":")
```

`list_keys` globs `*.parquet` recursively relative to `base_dir`, constructs the relative path
without extension as the stem, and applies `_filename_to_key` to recover the canonical key.

### 5. `load` and `delete` raise `KeyError`, not `StoreError`, for missing keys

`StoreError` is reserved for genuine I/O failures (corrupt file, permission denied).
`KeyError` signals "key absent" — consistent with the dict-like contract of the store.
`KeyError` message includes the key string for debuggability.

### 6. `delete` raises `KeyError` for a missing file

Consistent with the mapping-like contract: `delete` mirrors dict `pop` semantics. Callers can
use `exists(key)` to check before deleting if unconditional deletion is needed.

### 7. Docstrings

All public methods document `Args`, `Returns`, `Raises` (all exception types and conditions), and
include the key format contract in the class-level docstring. The existing `StoreError`-raising
paths also receive explicit `Raises` entries.

---

## Implementation Steps

### Step 1: Write this plan document (complete before any code changes) ✓

Save `docs/plans/phase1_data_pipeline/phase1.2-storage-layer.md`.

### Step 2: Record baseline state

```bash
git branch --show-current          # confirm: feature/phase-1-data-pipeline
git status                         # confirm: only pre-existing modifications
uv run python -m pytest tests/unit/config/ tests/unit/data/ \
    tests/unit/features/ tests/unit/risk/ -v   # record baseline pass/fail
```

### Step 3: Update `store.py`

Changes in order:

1. Add module-level helpers:
   - `_validate_key(key: str) -> None` — raises `ValueError` on empty / traversal
   - `_key_to_filename(key: str) -> str` — percent-encodes `:`
   - `_filename_to_key(stem: str) -> str` — decodes `%3A` → `:`
2. Update `__init__`: parameter unchanged (`base_dir: Path`); no functional change needed
3. Update `save`:
   - Rename `name` → `key`
   - Call `_validate_key(key)` at top
   - Use `_key_to_filename(key)` for path construction
   - Change return type to `None`; remove `return path`
   - Update docstring: add `Raises: ValueError` for invalid key
4. Update `load`:
   - Rename `name` → `key`
   - Call `_validate_key(key)` at top
   - Use `_key_to_filename(key)` for path construction
   - Change `raise StoreError(...)` for missing → `raise KeyError(key)`
   - Update docstring: change `StoreError` missing-key entry to `KeyError`
5. Update `exists`:
   - Rename `name` → `key`
   - Call `_validate_key(key)` at top
   - Use `_key_to_filename(key)` for path construction
6. Update `list_keys`:
   - Glob `**/*.parquet` relative to `base_dir` for recursive key discovery
   - Construct relative stem (path relative to `base_dir`, strip `.parquet` suffix)
   - Apply `_filename_to_key` to each stem
   - Return sorted list
7. Add `delete(self, key: str) -> None`:
   - Call `_validate_key(key)` at top
   - Construct path via `_key_to_filename(key)`
   - If not exists: `raise KeyError(key)`
   - `path.unlink()`; wrap in try/except for `StoreError` on failure
   - Log `info` on success
   - Add to `__all__`

### Step 4: Create `tests/unit/data/__init__.py`

Empty file (package marker).

### Step 5: Create `tests/unit/data/test_store.py`

Write 8 unit tests using the `tmp_path` pytest fixture:

| # | Test name | Assertion |
| --- | --- | --- |
| 1 | `test_round_trip_preserves_datetime_index_utc` | Load after save; index is `DatetimeIndex`, tz is UTC, name is `"datetime"` |
| 2 | `test_round_trip_preserves_column_dtypes` | `float64`, `int64`, `object` columns survive parquet round-trip |
| 3 | `test_save_returns_none` | `save(...)` return value is `None` |
| 4 | `test_overwrite_does_not_raise` | Second `save` with same key succeeds and load returns new data |
| 5 | `test_load_raises_key_error_for_missing_key` | `load("nonexistent")` raises `KeyError` |
| 6 | `test_exists_false_before_save_true_after` | `exists` → `False`; `save`; `exists` → `True` |
| 7 | `test_list_keys_returns_sorted_canonical_keys` | Save `"SET:AOT"` and `"SET:ADVANC"`; `list_keys()` == `["SET:ADVANC", "SET:AOT"]` |
| 8 | `test_delete_removes_file_second_delete_raises` | Save, delete, `exists` → `False`; second `delete` raises `KeyError` |

### Step 6: Run verification suite (see Verification Addendum)

### Step 7: Update `PLAN.md` and this document with completion notes; commit

---

## Verification Addendum

Run in this exact order:

```bash
# Confirm correct branch before any edits
git branch --show-current   # must be: feature/phase-1-data-pipeline

# After implementation — focused storage layer tests
uv run python -m pytest tests/unit/data/test_store.py -v   # must: 8 passed

# Type check
uv run mypy src/csm/data/store.py   # must: exit 0

# Lint and format
uv run ruff check src/csm/data/store.py          # must: exit 0
uv run ruff format --check src/csm/data/store.py # must: exit 0

# Full unit suite — confirm no regressions
uv run python -m pytest tests/unit/config/ tests/unit/data/ \
    tests/unit/features/ tests/unit/risk/ -v
# Expected: same 3 pre-existing failures; no new failures; 22 passed (14 + 8 new)
```

---

## File Changes

| File | Action | Description |
| --- | --- | --- |
| `src/csm/data/store.py` | MODIFY | Key validation, percent-encoding, `delete`, fix return/error types |
| `tests/unit/data/__init__.py` | CREATE | Package marker |
| `tests/unit/data/test_store.py` | CREATE | 8 unit tests for all `ParquetStore` public methods |
| `docs/plans/phase1_data_pipeline/phase1.2-storage-layer.md` | CREATE | This document |
| `docs/plans/phase1_data_pipeline/PLAN.md` | MODIFY | Phase 1.2 status + completion notes |

---

## Success Criteria

- [x] `save(key, df)` returns `None`
- [x] `save` overwrites without error if key already exists
- [x] `save` writes to `{base_dir}/{quote(key, safe="/")}.parquet`
- [x] `save` raises `ValueError` for empty, whitespace-only, backslash, or traversal keys
- [x] `load(key)` raises `KeyError` for a missing key (not `StoreError`)
- [x] `load(key)` restores `DatetimeIndex` with UTC timezone after round-trip
- [x] `load(key)` preserves `float64` and `int64` column dtypes
- [x] `exists(key)` → `False` before save; `True` after save
- [x] `list_keys()` → sorted canonical keys with `:` restored (e.g. `["SET:ADVANC", "SET:AOT"]`)
- [x] `delete(key)` removes file; subsequent `exists` → `False`
- [x] `delete` raises `KeyError` for a key that was never saved
- [x] `uv run python -m pytest tests/unit/data/test_store.py -v` — 8 passed
- [x] `uv run mypy src/csm/data/store.py` exits 0
- [x] `uv run ruff check src/csm/data/store.py` exits 0
- [x] No regressions in pre-existing unit tests (3 pre-existing failures unchanged)

---

## Completion Notes

### Summary

Phase 1.2 complete. `ParquetStore` now implements the full CRUD surface specified in the master
plan, with two improvements over the original spec:

1. **Reversible percent-encoding** (`urllib.parse.quote/unquote`) instead of the plan's
   naive `_` substitution — eliminates key collision and is fully platform-safe.
2. **Key validation** (`_validate_key`) rejects empty keys, backslash separators, and `..`
   path-traversal components before any I/O occurs.

8 unit tests pass. Type checking (`mypy`) and linting (`ruff`) exit 0. No regressions in the
pre-existing test suite.

### Issues Encountered

1. **Key encoding ambiguity in original plan** — the plan specified replacing `:` with `_` in
   filenames and reversing via `stem.replace("_", ":", 1)`. This is ambiguous for keys containing
   literal `_` before the first `:` (e.g. `FX_IDC:EURUSD`), and creates silent collisions between
   keys `SET:AOT` and `SET_AOT`. Replaced with `urllib.parse.quote/unquote` which is fully
   reversible and handles `%` in keys correctly.

2. **`object` dtype not preserved by pyarrow** — pyarrow encodes `object` string columns using
   its native `string` type; pandas reads them back as `pd.StringDtype` (alias `str`) rather than
   `object`. The dtype round-trip test was updated to use `pd.api.types.is_string_dtype()` instead
   of a strict `dtype == "object"` assertion.

3. **Synchronous I/O vs. async-first rule** — the project instructions require async-first I/O,
   but `ParquetStore` wraps synchronous pyarrow operations. Making it async would cascade
   `async`/`await` through `FeaturePipeline`, `MomentumBacktest`, and their tests, all out of
   scope for Phase 1.2. Documented as an explicit architectural exception in the module docstring,
   with the `asyncio.to_thread()` wrapper pattern for callers that need non-blocking behaviour.

4. **`path.exists()` vs. `path.is_file()`** — original implementation used `path.exists()` which
   would return `True` for a directory named `foo.parquet`. Changed to `path.is_file()` throughout
   for strict presence checking.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Sonnet 4.6)
**Status:** Complete
**Completed:** 2026-04-22
