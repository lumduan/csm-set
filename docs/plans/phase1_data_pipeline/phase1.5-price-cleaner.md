# Phase 1.5 — Price Cleaner

**Feature:** Data Pipeline — Price Cleaner
**Branch:** `feature/phase-1-data-pipeline`
**Created:** 2026-04-22
**Status:** Complete
**Completed:** 2026-04-22
**Depends On:** Phase 1.4 — Universe Builder (Complete)

> **Document type:** Combined plan + implementation report. Written before coding
> (plan sections), then updated after coding (completion notes, checked criteria).

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Gap Analysis](#gap-analysis)
5. [Design Decisions](#design-decisions)
6. [DataFrame Contract](#dataframe-contract)
7. [Settings and Constants Contract](#settings-and-constants-contract)
8. [Implementation Steps](#implementation-steps)
9. [Verification Addendum](#verification-addendum)
10. [File Changes](#file-changes)
11. [Success Criteria](#success-criteria)
12. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 1.5 delivers `PriceCleaner` — the component responsible for standardising raw per-symbol
OHLCV DataFrames before they are used in any signal calculation or backtest. It applies three
sequential cleaning steps: forward-fill short trading gaps, drop symbols with insufficient
data coverage, and winsorise extreme daily close returns. The class is a pure transform with
no I/O — it takes a DataFrame and returns a DataFrame (or `None` if the symbol is dropped).

### Parent Plan Reference

- `docs/plans/phase1_data_pipeline/PLAN.md` — Phase 1.5 section

### Key Deliverables

1. **`src/csm/data/cleaner.py`** — `PriceCleaner` with `forward_fill_gaps()`,
   `drop_low_coverage()`, `winsorise_returns()`, and `clean()`.
2. **`tests/unit/data/test_cleaner.py`** — 6 unit tests covering all cleaning steps,
   coverage check, and pipeline order.

---

## AI Prompt

The following prompt was used to initiate this implementation phase:

```text
🎯 Objective
Implement Phase 1.5 — Price Cleaner for the CSM-SET project by following a rigorous
plan-before-code workflow, including documentation and progress tracking.

📋 Context
- The CSM-SET project is a cross-sectional momentum strategy system for the SET market.
- The user is currently moving to Phase 1.5 — Price Cleaner, as outlined in
  docs/plans/phase1_data_pipeline/PLAN.md.
- The previous phase (1.4 — Universe Builder) is documented in
  docs/plans/phase1_data_pipeline/phase1.4-universe-builder.md.
- The workflow requires careful planning before coding, with the plan documented in a markdown
  file at docs/plans/phase1_data_pipeline/phase1.5-price-cleaner.md.
- The plan markdown should include the prompt used for this phase, following the format in
  docs/plans/examples/phase1-sample.md.
- After implementation, documentation must be updated with progress notes and checkmarks.
- All changes must be committed when the job is complete.

🔧 Requirements
- Thoroughly read and understand the docs, focusing on Phase 1.5 — Price Cleaner in
  docs/plans/phase1_data_pipeline/PLAN.md.
- Review the previous implementation in docs/plans/phase1_data_pipeline/phase1.4-universe-builder.md
  for context and architectural continuity.
- Plan the implementation before coding, and document the plan in
  docs/plans/phase1_data_pipeline/phase1.5-price-cleaner.md, including the prompt.
- Implement the Price Cleaner according to the plan, ensuring:
  - Type safety (explicit type annotations, Pydantic models)
  - Async/await patterns for I/O
  - Comprehensive error handling and logging
  - Unit tests for all cleaning logic and edge cases
  - Data saved to the appropriate cleaned price store
  - Output: cleaned price data, with all filters and corrections applied as per the plan
- Update docs/plans/phase1_data_pipeline/PLAN.md and
  docs/plans/phase1_data_pipeline/phase1.5-price-cleaner.md with progress notes, completion
  checkmarks, and any issues encountered.
- Commit all changes when the job is complete.
```

---

## Scope

### In Scope (Phase 1.5)

| Component | Description | Status |
| --- | --- | --- |
| `cleaner.py` — `forward_fill_gaps(df, max_gap_days)` | ffill NaN close ≤ max_gap_days; leave longer gaps as NaN | Complete |
| `cleaner.py` — `drop_low_coverage(df, min_coverage, window_years)` | Return None if any rolling year has > (1-min_coverage) missing bars | Complete |
| `cleaner.py` — `winsorise_returns(df, lower, upper)` | Clip extreme daily close returns at percentile bounds; reconstruct close | Complete |
| `cleaner.py` — `clean(df)` | Pipeline: fill → coverage check → winsorise; returns None if dropped | Complete |
| `tests/unit/data/test_cleaner.py` | 6 unit tests per PLAN.md specification | Complete |

### Out of Scope (Phase 1.5)

- Bulk Fetch Script — Phase 1.6
- Data Quality Notebook — Phase 1.7
- Cleaning of open/high/low/volume columns (only `close` is winsorised)
- Async I/O — PriceCleaner is a pure in-memory transform

---

## Gap Analysis

`src/csm/data/cleaner.py` already exists with a partial implementation using a different API.
This section records the delta between the existing code and the Phase 1.5 plan specification.

### `cleaner.py` gaps

| Item | Existing | Required by Plan | Action |
| --- | --- | --- | --- |
| API shape | Wide-matrix (`symbols` as columns) | Per-symbol OHLCV DataFrame (one symbol, OHLCV columns) | Replace |
| `forward_fill_gaps` | `ffill(limit=5)` on full wide matrix | `ffill(limit=max_gap_days)` on per-symbol OHLCV | Rename + refactor |
| `drop_low_coverage` | Column drop by overall missing ratio | Return `None` if any rolling year exceeds missing threshold | Rewrite |
| `winsorise_returns` | Reconstruct entire matrix from log returns | Clip pct_change returns at percentile bounds, back-compute close | Rewrite |
| `clean` return type | `pd.DataFrame` (never None) | `pd.DataFrame | None` (None = symbol dropped) | Update signature |
| `compute_returns` | Public instance method | Not in Phase 1.5 spec — removed | Remove |

### Test gaps

| Item | Existing | Required by Plan | Action |
| --- | --- | --- | --- |
| `test_forward_fill_gaps_fills_short_gap_leaves_long_gap` | Missing | Required (test 1) | Add |
| `test_drop_low_coverage_returns_none_for_high_missing` | Missing | Required (test 2) | Add |
| `test_drop_low_coverage_returns_df_for_acceptable_missing` | Missing | Required (test 3) | Add |
| `test_winsorise_returns_clips_extreme_outliers` | Missing | Required (test 4) | Add |
| `test_clean_returns_none_when_coverage_fails` | Missing | Required (test 5) | Add |
| `test_clean_applies_steps_in_order` | Missing | Required (test 6) | Add |
| Old wide-matrix tests | Two tests for old API | No longer applicable | Remove |

---

## Design Decisions

### 1. Per-symbol OHLCV DataFrame — not wide matrix

The existing `PriceCleaner` operated on a wide matrix where columns are symbols. The Phase 1.5
spec and the architecture diagram specify `PriceCleaner` as a per-symbol transform feeding
`data/processed/{SYMBOL}.parquet`. Per-symbol DataFrames are the natural boundary for all
other pipeline stages (ParquetStore, OHLCVLoader, UniverseBuilder), so the new API matches
that contract.

### 2. `forward_fill_gaps` applies to all OHLCV columns

The spec says "forward-fill NaN close prices". In practice, when a trading day is missing
(suspended stock, holiday), all OHLCV columns are NaN together. Forward-filling only close
would produce internally inconsistent rows (e.g., valid close but NaN volume). The
implementation calls `df.ffill(limit=max_gap_days)` on the full DataFrame. This is equivalent
to the spec intent while preserving OHLCV consistency.

### 3. `drop_low_coverage` uses rolling 252-bar windows

A "rolling year" is interpreted as a 252-trading-day window, not a 365-calendar-day window,
because OHLCV DataFrames carry trading-day bars only. For DataFrames shorter than
`window_years * 252` rows, the entire available history is checked instead (avoids all
short-history symbols being rejected at start-up when the store is partially populated).

### 4. `winsorise_returns` reconstructs full close series

When a return is clipped, the subsequent price level must be based on the adjusted value —
otherwise later returns inherit the original spike and the winsorisation has no lasting effect.
The implementation reconstructs the entire close series from the first valid close using the
clipped arithmetic returns. Non-NaN positions where the previous close is NaN (after a long
gap) restart reconstruction from the original close value.

### 5. Only `close` is modified by winsorisation

`open`, `high`, `low`, and `volume` are left unchanged. Adjusting all OHLCV columns to be
internally consistent after winsorisation is out of scope for Phase 1.5. Downstream signal
calculations use `close` only.

### 6. `PriceCleaner` is stateless

No `__init__` parameters. All method parameters are explicitly passed. This keeps the class
a thin namespace for related functions, consistent with the architecture note
"pure transform, no I/O".

---

## DataFrame Contract

Input and output DataFrames must conform to the OHLCV schema from PLAN.md:

| Field | Type | Constraint |
| --- | --- | --- |
| Index | `DatetimeIndex` | UTC or tz-aware, name = `"datetime"` |
| `open` | `float64` | > 0 |
| `high` | `float64` | ≥ open, ≥ close |
| `low` | `float64` | ≤ open, ≤ close |
| `close` | `float64` | > 0 (after cleaning) |
| `volume` | `float64` | ≥ 0 |

`clean()` returns `None` when the symbol is dropped by `drop_low_coverage`. The caller
must check for `None` before persisting to `data/processed/`.

---

## Settings and Constants Contract

`PriceCleaner` is stateless and reads no env vars. Default parameter values come from
`constants.py`:

| Name | Source | Value | Used as default for |
| --- | --- | --- | --- |
| `MIN_DATA_COVERAGE` | `constants.py` | `0.80` | `drop_low_coverage(min_coverage=…)` |

All other defaults (`max_gap_days=5`, `lower=0.01`, `upper=0.99`, `window_years=1`) are
hardcoded in method signatures per the plan specification. `Settings` is not required by
this phase.

---

## Implementation Steps

### Step 1: Write this plan document (complete before any code changes) ✓

### Step 2: Rewrite `src/csm/data/cleaner.py`

1. Replace class body with four new methods: `forward_fill_gaps`, `drop_low_coverage`,
   `winsorise_returns`, `clean`
2. Remove `compute_returns` — not in Phase 1.5 spec
3. Import `MIN_DATA_COVERAGE` from `constants.py`
4. Update module docstring

### Step 3: Rewrite `tests/unit/data/test_cleaner.py`

| # | Test name | What it verifies |
| --- | --- | --- |
| 1 | `test_forward_fill_gaps_fills_short_gap_leaves_long_gap` | 3-day gap filled; 6-day gap: first 5 positions filled, last 1 stays NaN |
| 2 | `test_drop_low_coverage_returns_none_for_high_missing` | 25% missing in 252-row window → None |
| 3 | `test_drop_low_coverage_returns_df_for_acceptable_missing` | 15% missing → DataFrame returned |
| 4 | `test_winsorise_returns_clips_extreme_outliers` | 80% return spike clipped to ≤ 99th percentile |
| 5 | `test_clean_returns_none_when_coverage_fails` | Full pipeline returns None for 25% missing |
| 6 | `test_clean_applies_steps_in_order` | Short gap filled AND outlier clipped in cleaned result |

### Step 4: Run verification suite (see below)

### Step 5: Update PLAN.md and this document; commit

---

## Verification Addendum

Run in this exact order:

```bash
# Focused cleaner tests
uv run python -m pytest tests/unit/data/test_cleaner.py -v   # must: 6 passed

# Type check
uv run mypy src/csm/data/cleaner.py   # must: exit 0

# Lint and format
uv run ruff check src/csm/data/cleaner.py           # must: exit 0
uv run ruff format --check src/csm/data/cleaner.py  # must: exit 0

# Full unit suite — confirm no regressions
uv run python -m pytest tests/unit/ -v
# Expected: 1 pre-existing failure (test_regime_transitions_on_known_price_series)
# All other tests must pass.
```

---

## File Changes

| File | Action | Description |
| --- | --- | --- |
| `src/csm/data/cleaner.py` | MODIFY | Rewrite to plan-spec per-symbol API |
| `tests/unit/data/test_cleaner.py` | MODIFY | Replace 2 old tests with 6 new tests |
| `docs/plans/phase1_data_pipeline/phase1.5-price-cleaner.md` | CREATE | This document |
| `docs/plans/phase1_data_pipeline/PLAN.md` | MODIFY | Phase 1.5 status + completion notes |

---

## Success Criteria

- [x] `forward_fill_gaps` fills a 3-day gap; leaves last day of a 6-day gap unfilled
- [x] `drop_low_coverage` returns `None` for a symbol with 25% missing in a 252-row window
- [x] `drop_low_coverage` returns `DataFrame` for a symbol with 15% missing
- [x] `winsorise_returns` clips an extreme 80% return spike down to ≤ 99th percentile
- [x] `clean` returns `None` when the symbol fails the coverage check
- [x] `clean` applies all steps in correct order (fill → coverage → winsorise)
- [x] `uv run python -m pytest tests/unit/data/test_cleaner.py -v` — 6 passed
- [x] `uv run mypy src/csm/data/cleaner.py` exits 0
- [x] `uv run ruff check src/csm/data/cleaner.py` exits 0
- [x] No new regressions beyond the pre-existing `test_regime` failure

---

## Completion Notes

### Summary

Phase 1.5 complete. `PriceCleaner` implements the full per-symbol OHLCV cleaning pipeline:
`forward_fill_gaps` (ffill with `limit=max_gap_days`), `drop_low_coverage` (rolling 252-bar
window check returning `None` on failure), `winsorise_returns` (clip arithmetic returns at
percentile bounds and reconstruct close series), and `clean` (orchestrates all three in
order). 6 unit tests pass. `mypy` and `ruff` exit 0. No new regressions introduced.

### Issues Encountered

1. **Existing API was wide-matrix** — The existing `PriceCleaner` operated on wide DataFrames
   (symbols as columns). Phase 1.5 replaces this with the per-symbol OHLCV API per the
   architecture diagram. The old `compute_returns` method was removed as it is not in the
   Phase 1.5 spec.

2. **`drop_low_coverage` short-history guard** — With fewer than `window_years * 252` rows,
   a rolling window would always return NaN counts. Added a guard: if history is shorter than
   one full window, check full-series coverage instead, so partially-populated stores don't
   incorrectly drop all symbols.

3. **`winsorise_returns` NaN chain handling** — Reconstruction loop resets at positions where
   the previous close is NaN (long gap boundary). Subsequent prices restart from their
   original close value until the chain continues from a non-NaN anchor.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Sonnet 4.6)
**Status:** Complete
**Completed:** 2026-04-22
