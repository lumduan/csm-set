# Phase 1.3 — tvkit Loader

**Feature:** Data Pipeline — tvkit OHLCV Loader
**Branch:** `feature/phase-1-data-pipeline`
**Created:** 2026-04-22
**Status:** Complete
**Completed:** 2026-04-22
**Depends On:** Phase 1.2 — Storage Layer (Complete)

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

Phase 1.3 delivers `OHLCVLoader` — a thin, testable async wrapper around tvkit's `OHLCV` API.
It is the only code in the pipeline that calls tvkit directly. All other components consume
DataFrames already on disk via `ParquetStore`. The loader enforces the public mode guard
(`DataAccessError` raised immediately when `CSM_PUBLIC_MODE=true`), bounds concurrent fetch
calls with an `asyncio.Semaphore`, retries transient network failures up to
`Settings.tvkit_retry_attempts` times, and returns DataFrames with a documented schema.

### Parent Plan Reference

- `docs/plans/phase1_data_pipeline/PLAN.md` — Phase 1.3 section

### Key Deliverables

1. **`src/csm/data/loader.py`** — `OHLCVLoader` with `fetch()` and `fetch_batch()`,
   semaphore concurrency control, transient-error retry, and public mode guard.
2. **`tests/unit/data/test_loader.py`** — All 6 unit tests passing (2 pre-existing fixed +
   2 new: batch failure isolation and retry).

---

## AI Prompt

The following prompt was used to initiate this implementation phase:

```text
🎯 Objective
Create a comprehensive implementation plan and execution workflow for Phase 1.3 — tvkit Loader of
the Data Pipeline Master Plan, following all architectural, documentation, and workflow standards.
The plan must be saved as a markdown file at docs/plans/phase1_data_pipeline/phase1.3-tvkit-loader.md,
include the full prompt used, and only begin implementation after the plan is complete. Upon
completion, update all relevant documentation files with progress notes and commit all changes.

📋 Context
- The project is a type-safe, async-first Python data pipeline for SET OHLCV data, using Pydantic
  for configuration and validation.
- The previous phase (Phase 1.2 — Storage Layer) is complete and documented at
  docs/plans/phase1_data_pipeline/phase1.2-storage-layer.md.
- The master plan and requirements for Phase 1.3 — tvkit Loader are detailed in
  docs/plans/phase1_data_pipeline/PLAN.md.
- All code must follow strict architectural, type safety, async, and documentation standards as
  outlined in the .github/instructions directory.
- The plan format reference is at docs/plans/examples/phase1-sample.md.

🔧 Requirements
- Read and understand docs/plans/phase1_data_pipeline/PLAN.md, focusing on Phase 1.3 — tvkit Loader.
- Review docs/plans/phase1_data_pipeline/phase1.2-storage-layer.md for context and integration points.
- Draft a detailed implementation plan for Phase 1.3 in markdown, saved as
  docs/plans/phase1_data_pipeline/phase1.3-tvkit-loader.md.
  - The plan must include: objectives, deliverables, step-by-step tasks, anticipated challenges,
    and the exact prompt used (for traceability).
  - Follow the format reference at docs/plans/examples/phase1-sample.md.
- Do not begin coding until the plan is complete and saved.
- After implementation, update both docs/plans/phase1_data_pipeline/PLAN.md and
  docs/plans/phase1_data_pipeline/phase1.3-tvkit-loader.md with progress notes, completion
  dates, and any issues encountered.
- All code must be type-safe, async-first, use Pydantic for all models/configuration, and include
  comprehensive docstrings and tests.
- Commit all changes with a clear, standards-compliant commit message.

📁 Code Context
- docs/plans/phase1_data_pipeline/PLAN.md (master plan and requirements)
- docs/plans/phase1_data_pipeline/phase1.2-storage-layer.md (previous phase, integration context)
- docs/plans/examples/phase1-sample.md (plan format reference)
- .github/instructions/ (coding, documentation, and workflow standards)

✅ Expected Output
- A new plan file at docs/plans/phase1_data_pipeline/phase1.3-tvkit-loader.md, following the
  required format and including the full prompt.
- Implementation of Phase 1.3 — tvkit Loader, fully type-safe, async, Pydantic-based, and tested.
- Updated docs/plans/phase1_data_pipeline/PLAN.md and
  docs/plans/phase1_data_pipeline/phase1.3-tvkit-loader.md with progress notes and completion details.
- All changes committed with a standards-compliant commit message.
```

---

## Scope

### In Scope (Phase 1.3)

| Component | Description | Status |
| --- | --- | --- |
| `loader.py` — `__init__(settings)` | Stores settings; creates `asyncio.Semaphore` | Complete |
| `loader.py` — `fetch(symbol, interval, bars)` | Public mode guard; retry loop; tvkit call; returns schema-validated DataFrame | Complete |
| `loader.py` — `fetch_batch(symbols, interval, bars)` | Public mode guard; concurrent fetch under semaphore; per-symbol failure isolation | Complete |
| `tests/unit/data/test_loader.py` | 6 unit tests: schema check, public mode guard (×2), batch isolation, retry | Complete |

### Out of Scope (Phase 1.3)

- `ParquetStore` integration — belongs to the bulk fetch script (Phase 1.6)
- Universe builder — Phase 1.4
- Price cleaner — Phase 1.5
- Integration smoke test against live tvkit (manual, skipped in CI)

---

## Gap Analysis

`src/csm/data/loader.py` already exists with a partial implementation. This section records the
delta between the existing code and the Phase 1.3 plan specification.

### `loader.py` gaps

| Item | Existing | Required by Plan | Action |
| --- | --- | --- | --- |
| `__init__` semaphore | absent | `asyncio.Semaphore(settings.tvkit_concurrency)` | Add |
| `fetch()` DatetimeIndex construction | `pd.to_datetime(series)` then `.tz_convert()` directly on Series — raises in pandas 2.x | Wrap in explicit `pd.DatetimeIndex()` before `.tz_convert()` | Fix |
| `fetch()` index name | not set | `"datetime"` | Set `index.name = "datetime"` |
| `fetch()` empty-result DataFrame | `RangeIndex`, no tz, no name | Empty `DatetimeIndex` with `tz=Asia/Bangkok`, `name="datetime"` | Fix |
| `fetch()` retry logic | absent — single attempt, all exceptions wrapped as `FetchError` | Retry transient errors up to `tvkit_retry_attempts` retries; fail-fast for non-transient | Add |
| `fetch_batch()` semaphore | absent — unlimited concurrent tasks | `async with self._semaphore:` inside each task | Add |

### Test gaps

| Item | Existing | Required by Plan | Action |
| --- | --- | --- | --- |
| `test_fetch_returns_correct_dataframe_schema` | FAILING (DatetimeIndex bug) | PASS | Fix implementation |
| `test_fetch_batch_returns_dict_keyed_by_symbol` | FAILING (DatetimeIndex bug propagates via FetchError) | PASS | Fix implementation |
| `test_fetch_batch_continues_after_symbol_failure` | absent | required | Add |
| `test_fetch_retries_on_transient_error` | absent | required | Add |

### Baseline state

```bash
# Recorded before any edits:
git branch --show-current   # feature/phase-1-data-pipeline
git status                  # clean
uv run python -m pytest tests/unit/ -v
# Result: 3 pre-existing failures (test_loader × 2, test_regime × 1); 27 passed
```

The pre-existing `test_regime` failure is unrelated to the loader and must not change after this
phase. The 2 `test_loader` failures are being fixed in this phase.

---

## Design Decisions

### 1. DatetimeIndex timezone — Bangkok, not UTC

The master plan spec (`PLAN.md`) states the output DataFrame should have a UTC index. However,
the pre-written tests assert `str(frame.index.tz) == "Asia/Bangkok"`, and the loader intentionally
converts via `TIMEZONE = "Asia/Bangkok"` from `constants.py`. The tests are the authoritative
contract for this phase; UTC is the storage-layer concern (`ParquetStore` normalises on write/read).

**Decision:** keep `Asia/Bangkok` as the loader's output timezone to match the test contract.
This deviation from the plan spec is recorded here and in the Completion Notes.

### 2. DatetimeIndex construction — explicit `pd.DatetimeIndex()`

`pd.to_datetime(series, utc=True)` returns a `pd.Series` in pandas 2.x, not a `pd.DatetimeIndex`.
`pd.Series` does not have a `.tz_convert()` method in pandas 2.0+ (removed; use `.dt.tz_convert()`
instead). Calling `.tz_convert()` directly on the Series raises a pandas error at runtime.

**Fix:** wrap the `pd.to_datetime` result in `pd.DatetimeIndex()` before calling `.tz_convert()`:

```python
raw_index = pd.to_datetime(frame.pop("timestamp"), utc=True)
index: pd.DatetimeIndex = pd.DatetimeIndex(raw_index).tz_convert(TIMEZONE)
index.name = "datetime"
frame.index = index
```

### 3. Empty-result contract — consistent schema

The existing empty-result guard returns `pd.DataFrame(columns=[...])` with a default `RangeIndex`.
This breaks the schema contract that `fetch()` always returns a `DatetimeIndex` (tz, name).

**Fix:**

```python
if frame.empty:
    idx: pd.DatetimeIndex = pd.DatetimeIndex([], tz=TIMEZONE, name="datetime")
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"], index=idx)
```

### 4. Semaphore created in `__init__`

`asyncio.Semaphore(n)` in Python 3.10+ does not require a running event loop at construction
(the `loop` parameter was removed in 3.10). Creating it in `__init__` is safe, keeps the class
self-contained, and avoids re-creating a semaphore on every `fetch_batch` call.

### 5. `tvkit_retry_attempts` semantics — retries, not total attempts

`Settings.tvkit_retry_attempts` (default `3`) means the number of **retries after the first
attempt**. Total attempts = `tvkit_retry_attempts + 1`.

- `tvkit_retry_attempts = 0` → 1 attempt total, no retry
- `tvkit_retry_attempts = 3` → 4 attempts total (1 initial + 3 retries)

The retry loop runs `for attempt in range(settings.tvkit_retry_attempts + 1)`.

### 6. Transient vs. non-transient error classification

Retryable failures are caused by transient infrastructure conditions, not by bad inputs or
deterministic upstream failures. The `_TRANSIENT_EXCEPTIONS` tuple captures the retryable set:

```python
_TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    asyncio.TimeoutError,
    OSError,          # covers ConnectionError, ConnectionResetError, BrokenPipeError
    EOFError,         # WebSocket close mid-stream
    StreamConnectionError,  # tvkit reconnect exhausted — tvkit.api.chart.exceptions
)
```

The retry loop structure:

```python
for attempt in range(self._settings.tvkit_retry_attempts + 1):
    try:
        # ... tvkit call ...
        break  # success — exit retry loop
    except _TRANSIENT_EXCEPTIONS as exc:
        if attempt == self._settings.tvkit_retry_attempts:
            raise FetchError(f"... all retries exhausted") from exc
        logger.warning("Transient error on attempt %d/%d, retrying", ...)
        continue
    except Exception as exc:
        # Non-transient: AuthError, NoHistoricalDataError, RangeTooLargeError,
        # SegmentedFetchError, ValueError, and any other exception — fail fast.
        raise FetchError(f"...") from exc
```

Only `StreamConnectionError` is imported from `tvkit.api.chart.exceptions`. The other non-transient
tvkit exceptions (`AuthError`, `NoHistoricalDataError`, `RangeTooLargeError`, `SegmentedFetchError`)
fall into the generic `except Exception` branch — no branch-specific logic needed for them.

### 7. No `TransientFetchError` class

The master plan lists `TransientFetchError` as optional. Adding it would introduce an untested,
unexposed exception type with no caller distinction from `FetchError`. Omitted.

### 8. `fetch_batch` result ordering

`asyncio.gather(*tasks)` is guaranteed to return results in the **same order as the input
awaitables** (i.e. task-creation order, which equals input `symbols` order), regardless of
task completion order. The dict comprehension builds the result dict from `gather`'s output
list in that same order. Python dicts preserve insertion order (3.7+), so the result dict
entries appear in the same order as the input `symbols` list, minus any failed symbols.

Callers can rely on this ordering, though correctness must not depend on it (the result is
keyed by symbol, not positional).

### 9. Output DataFrame contract

Every `pd.DataFrame` returned by `fetch()` conforms to this schema:

| Field | dtype | Constraint | Behaviour |
| --- | --- | --- | --- |
| Index | `DatetimeIndex` | `tz = Asia/Bangkok`, `name = "datetime"` | Ascending sorted |
| `open` | `float64` | > 0 | — |
| `high` | `float64` | ≥ open, ≥ close | — |
| `low` | `float64` | ≤ open, ≤ close | — |
| `close` | `float64` | > 0 | — |
| `volume` | `float64` | ≥ 0 | — |

- **Row order:** ascending by datetime (`sort_index()` applied before return).
- **Empty result:** returns a zero-row DataFrame with an empty `DatetimeIndex`
  (tz = `Asia/Bangkok`, name = `"datetime"`) — consistent with the non-empty schema.
- **Duplicate timestamps:** not deduplicated by the loader; downstream `PriceCleaner` is
  responsible for handling duplicates if they occur in raw tvkit data.

---

## Implementation Steps

### Step 1: Write this plan document (complete before any code changes) ✓

Save `docs/plans/phase1_data_pipeline/phase1.3-tvkit-loader.md`.

### Step 2: Record baseline state

```bash
git branch --show-current   # verify: feature/phase-1-data-pipeline
git status                  # verify: clean working tree
uv run python -m pytest tests/unit/ -v
# Expected: 3 failures (test_loader × 2, test_regime × 1); 27 passed
```

### Step 3: Update `loader.py`

Changes in order:

1. Add import: `from tvkit.api.chart.exceptions import StreamConnectionError`
2. Verify import `from csm.data.exceptions import DataAccessError, FetchError` (already present)
3. Add module-level `_TRANSIENT_EXCEPTIONS` tuple (see Design Decision §6)
4. Update `OHLCVLoader.__init__`:
   - Add `self._semaphore: asyncio.Semaphore = asyncio.Semaphore(settings.tvkit_concurrency)`
5. Rewrite `OHLCVLoader.fetch()`:
   - Keep public mode guard at top (unchanged)
   - Fix empty-result guard: return proper empty `DatetimeIndex` DataFrame (Design Decision §3)
   - Replace bare try/except with retry loop (Design Decision §6)
   - Fix `DatetimeIndex` construction (Design Decision §2): wrap in `pd.DatetimeIndex()`
   - Set `index.name = "datetime"`
6. Update `OHLCVLoader.fetch_batch()`:
   - Add `async with self._semaphore:` inside `_fetch_symbol` wrapping the `await self.fetch(...)` call

### Step 4: Update `tests/unit/data/test_loader.py`

Add two tests:

| # | Test name | Assertion |
| --- | --- | --- |
| 5 | `test_fetch_batch_continues_after_symbol_failure` | One fake raises `FetchError` on first call; second symbol returns DataFrame; result dict contains only the successful symbol |
| 6 | `test_fetch_retries_on_transient_error` | Fake raises `OSError` twice then returns bars; `settings` override with `tvkit_retry_attempts=2`; `fetch` returns valid DataFrame on 3rd attempt |

For test 6, the monkeypatched `OHLCV` class tracks call count and raises `OSError` for the
first two attempts, then returns valid `_FakeBar` data on attempt 3.

### Step 5: Run verification suite (see Verification Addendum)

### Step 6: Update `PLAN.md` and this document with completion notes; commit

---

## Verification Addendum

Run in this exact order:

```bash
# Verify branch and working tree
git branch --show-current   # must be: feature/phase-1-data-pipeline
git status                  # must be: clean (only planned files modified)

# Focused loader tests
uv run python -m pytest tests/unit/data/test_loader.py -v   # must: 6 passed

# Type check
uv run mypy src/csm/data/loader.py   # must: exit 0

# Lint and format
uv run ruff check src/csm/data/loader.py          # must: exit 0
uv run ruff format --check src/csm/data/loader.py # must: exit 0

# Unit suite — confirm no regressions
uv run python -m pytest tests/unit/ -v
# Expected: 1 pre-existing failure (test_regime); all other tests pass

# Full suite (repo-wide standard) — API tests may require extra setup; failures beyond
# the pre-existing set indicate a regression introduced in this phase
uv run python -m pytest tests/ -v
```

Note: `tests/unit/` is the primary gate for this phase. Running the full `tests/` suite
(including API integration tests) is included for repo-wide compliance but any pre-existing
failures outside `tests/unit/` are out of scope for Phase 1.3.

---

## File Changes

| File | Action | Description |
| --- | --- | --- |
| `src/csm/data/loader.py` | MODIFY | Fix DatetimeIndex bug; fix empty-result; add semaphore; add retry loop |
| `tests/unit/data/test_loader.py` | MODIFY | Add 2 tests: batch failure isolation, retry |
| `docs/plans/phase1_data_pipeline/phase1.3-tvkit-loader.md` | CREATE | This document |
| `docs/plans/phase1_data_pipeline/PLAN.md` | MODIFY | Phase 1.3 status + completion notes |

---

## Success Criteria

- [x] `fetch("SET:AOT", "1D", 2)` returns DataFrame with columns `["open", "high", "low", "close", "volume"]`
- [x] `fetch` result has `DatetimeIndex` with `tz = Asia/Bangkok` and `name = "datetime"`
- [x] Rows are sorted ascending by datetime
- [x] Empty result returns a zero-row DataFrame with a matching `DatetimeIndex` (tz, name)
- [x] `fetch` raises `DataAccessError` immediately when `public_mode=True` (no tvkit call)
- [x] `fetch_batch` raises `DataAccessError` immediately when `public_mode=True`
- [x] `fetch_batch` returns only successfully fetched symbols; failed symbols absent from result dict
- [x] `fetch` retries up to `tvkit_retry_attempts` times on transient errors; returns DataFrame on final successful attempt
- [x] `uv run python -m pytest tests/unit/data/test_loader.py -v` — 7 passed (6 planned + 1 extra)
- [x] `uv run mypy src/csm/data/loader.py` exits 0
- [x] `uv run ruff check src/csm/data/loader.py` exits 0
- [x] No new regressions in pre-existing unit tests (1 pre-existing failure: `test_regime`)

---

## Completion Notes

### Summary

Phase 1.3 complete. `OHLCVLoader` now implements the full contract specified in the master plan:
public mode guard, retry loop for transient failures, semaphore-bounded concurrency in
`fetch_batch`, and a correctly constructed `DatetimeIndex`. 7 unit tests pass. Type checking
(`mypy`) and linting (`ruff`) exit 0. No regressions in the pre-existing test suite.

### Issues Encountered

1. **`pd.to_datetime` returns Series, not DatetimeIndex in pandas 2.x** — The original
   `loader.py` called `.tz_convert()` directly on the `pd.Series` returned by
   `pd.to_datetime(series, utc=True)`. In pandas 2.0+, `Series.tz_convert()` was removed; the
   call raised a runtime error that was swallowed as `FetchError`. Fixed by wrapping the result
   in `pd.DatetimeIndex()` before calling `.tz_convert()`.

2. **Empty-result DataFrame had inconsistent index schema** — The original empty-result guard
   returned `pd.DataFrame(columns=[...])` with a default `RangeIndex`. This broke the contract
   that every `fetch()` return value has a `DatetimeIndex` (tz, name). Fixed to return an
   empty `DatetimeIndex([], tz=TIMEZONE, name="datetime")`.

3. **Timezone deviation from master plan spec** — `PLAN.md` specifies UTC for the output
   `DatetimeIndex`. The pre-written tests assert `"Asia/Bangkok"`. The test contract takes
   precedence; the loader keeps Bangkok timezone consistent with `constants.TIMEZONE`. The
   UTC contract in `PLAN.md` is the storage-layer concern (`ParquetStore` round-trip).

4. **`ruff` B009 — `getattr` with constant attribute** — The original code used `getattr(bar,
   "timestamp")` etc. for all six `OHLCVBar` field accesses. Replaced with direct attribute
   access (`bar.timestamp`, `bar.open`, …). `mypy` confirms the fields are typed on `OHLCVBar`.

5. **7 tests, not 6** — An extra test (`test_fetch_raises_fetch_error_when_all_retries_exhausted`)
   was added beyond the plan spec to verify the exhausted-retry path explicitly. All 7 pass.

---

**Document Version:** 1.1
**Author:** AI Agent (Claude Sonnet 4.6)
**Status:** Complete
**Completed:** 2026-04-22
