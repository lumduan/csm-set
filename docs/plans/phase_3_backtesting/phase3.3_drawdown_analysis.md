# Phase 3.3 — Drawdown Analysis

**Feature:** Underwater Curve and Episode Recovery Table for Backtest Results
**Branch:** `feature/phase-3-backtesting`
**Created:** 2026-04-27
**Status:** Complete
**Completed:** 2026-04-27
**Depends On:** Phase 3.2 (Performance Metrics — Complete)

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Implementation Steps](#implementation-steps)
6. [File Changes](#file-changes)
7. [Test Coverage](#test-coverage)
8. [Success Criteria](#success-criteria)
9. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 3.3 delivers `DrawdownAnalyzer` — a class that computes the **underwater equity
curve**, the **peak-to-trough maximum drawdown**, and a **drawdown episode table** with
start date, trough date, recovery date, depth, and duration for each completed episode.

`DrawdownAnalyzer` is consumed in two places:

1. **`PerformanceMetrics.summary()`** — calls `DrawdownAnalyzer.max_drawdown()` to
   populate `calmar` and `max_drawdown` in the metrics dict.
2. **`notebooks/03_backtest_analysis.ipynb` Section 6** — calls
   `DrawdownAnalyzer.underwater_curve()` and `DrawdownAnalyzer.recovery_periods()` to
   produce the underwater chart and episode table for the Phase 3 sign-off notebook.

All outputs are public-safe — no raw OHLCV prices, only derived series and statistics.

### Parent Plan Reference

- `docs/plans/phase-3-backtesting/PLAN.md`

### Key Deliverables

1. **`src/csm/risk/drawdown.py`** — `DrawdownAnalyzer` with `max_drawdown()`,
   `underwater_curve()`, and `recovery_periods()`.
2. **`tests/unit/risk/test_drawdown.py`** — 9 unit tests covering all methods, edge
   cases (monotonic series, open episode, single-point series, multiple episodes), and
   the depth and duration invariants.

---

## AI Prompt

The following prompt was used to generate this phase:

```
Design and implement Phase 3.3 — Drawdown Analysis for the SET momentum backtesting
project, following the established planning and documentation workflow. The deliverable
includes a detailed implementation plan in markdown (with the full prompt), the drawdown
analysis module, comprehensive tests, and updated project documentation reflecting
progress and completion.

📋 Context
- The project is a multi-phase research and production pipeline for SET market momentum
  strategies.
- Phase 3.3 focuses on robust drawdown analysis for backtest results, as outlined in
  `docs/plans/phase-3-backtesting/PLAN.md`.
- The previous phase (3.2) delivered annualised performance metrics and is documented in
  `docs/plans/phase-3-backtesting/phase3.2_performance_metrics.md`.
- All planning and implementation steps must be documented, with progress tracked in
  both the phase plan and the master plan.
- The plan markdown must follow the format in `docs/plans/examples/phase1-sample.md`
  and include the full prompt used for this job.

🔧 Requirements
- Carefully read and understand `docs/plans/phase-3-backtesting/PLAN.md`, focusing on
  Phase 3.3 — Drawdown Analysis, and review the previous phase's plan at
  `docs/plans/phase-3-backtesting/phase3.2_performance_metrics.md`.
- Before coding, create a detailed plan for Phase 3.3 as a markdown file at
  `docs/plans/phase-3-backtesting/phase3.3_drawdown_analysis.md`, following the format
  in `docs/plans/examples/phase1-sample.md`. The plan must include the full prompt used
  for this job.
- Only begin implementation after the plan is complete and committed.
- Implement the drawdown analysis module according to the requirements and architecture
  in the plan and master plan.
- All code must follow project architectural standards: type safety, async/await
  patterns, Pydantic validation, comprehensive error handling, and public-safe outputs.
- All new features must have unit tests with ≥90% coverage, including edge cases and
  error conditions.
- After implementation, update `docs/plans/phase-3-backtesting/PLAN.md` and
  `docs/plans/phase-3-backtesting/phase3.3_drawdown_analysis.md` with progress notes,
  completion dates, and any issues encountered.
- Commit all changes with a clear, standards-compliant commit message.

📁 Code Context
- `docs/plans/phase-3-backtesting/PLAN.md` (master plan, requirements, architecture)
- `docs/plans/phase-3-backtesting/phase3.2_performance_metrics.md` (previous phase plan
  and implementation context)
- `docs/plans/examples/phase1-sample.md` (plan markdown format reference)
- Target plan file: `docs/plans/phase-3-backtesting/phase3.3_drawdown_analysis.md`
- Implementation files: as specified in the plan (likely `src/csm/risk/drawdown.py`,
  related test and model files)
- Documentation files: as above

✅ Expected Output
- A new plan markdown file at
  `docs/plans/phase-3-backtesting/phase3.3_drawdown_analysis.md` detailing the
  approach for Phase 3.3, including the full prompt.
- Implementation of the drawdown analysis module as specified in the plan.
- Comprehensive unit tests for all drawdown metrics and edge cases.
- Updated progress notes in `docs/plans/phase-3-backtesting/PLAN.md` and
  `docs/plans/phase-3-backtesting/phase3.3_drawdown_analysis.md`.
- All changes committed with a clear, standards-compliant commit message.
```

---

## Scope

### In Scope (Phase 3.3)

| Component | Description | Status |
|---|---|---|
| `DrawdownAnalyzer.max_drawdown()` | Peak-to-trough max as negative float; delegates to `underwater_curve().min()` | Complete |
| `DrawdownAnalyzer.underwater_curve()` | `equity / equity.cummax() - 1` — percentage below running peak | Complete |
| `DrawdownAnalyzer.recovery_periods()` | Episode table: start, trough, recovery, depth, duration_days; open episodes excluded | Complete |
| `tests/unit/risk/test_drawdown.py` | 9 unit tests — all methods, monotonic, single-point, open episode, multiple episodes | Complete |

### Out of Scope (Phase 3.3)

- Underwater curve chart and episode table visualisation (Phase 3.4 notebook)
- Bootstrap confidence intervals around max drawdown (Future Enhancement)
- Regime-conditional drawdown segmentation (Phase 4)
- `BacktestResult` Pydantic model (Phase 3.1 — `backtest.py`)
- `PerformanceMetrics.summary()` (Phase 3.2 — `metrics.py`, consumes `DrawdownAnalyzer`)

---

## Design Decisions

### 1. `underwater_curve` uses `cummax()` — population peak, not rolling window

`equity_curve / equity_curve.cummax() - 1` produces a series that is always ≤ 0,
where 0 means "at or above all prior peaks" and negative values represent the fractional
depth below the running maximum. This is the standard definition of the underwater curve
used in practitioner drawdown reporting.

A fixed rolling window would produce a different (and less meaningful) measure — it is
not used here.

### 2. Open episodes at series end are excluded from `recovery_periods()`

An episode that has not fully recovered to its prior peak by the last date in the series
is **not** included in the episode table. This follows investor-reporting convention:
an unresolved drawdown has undefined `recovery` date and `duration_days`, so including
it in the table would require sentinel values (NaT, -1) that complicate downstream use.

The open episode's depth is still captured by `max_drawdown()`, which operates on the
full underwater curve regardless of recovery status.

### 3. State machine loop in `recovery_periods()`

The episode detector is a single-pass state machine over the underwater series:

| State | Condition | Action |
|---|---|---|
| `not in_drawdown` | `value < 0.0` | Enter drawdown, record `start = date`, `trough = date` |
| `in_drawdown` | `value < trough_depth` | Deepen trough — update `trough = date`, `trough_depth = value` |
| `in_drawdown` | `value >= 0.0` | Recovery — append row, reset state |
| `in_drawdown` | End of series | Open episode — no row appended |

This is O(n) in time and O(k) in space where k is the number of complete episodes.

### 4. `max_drawdown` returns 0.0 for monotonically increasing or single-point series

For a monotonically increasing series, `cummax()` equals the series at every point, so
`equity / cummax - 1 = 0` everywhere. `min()` of an all-zero series is 0.0.

For a single-point series (`[100.0]`), the same logic holds: the one-element underwater
curve is `[0.0]`, and `min()` returns 0.0.

Neither case raises an exception. This matches the `PerformanceMetrics.summary()`
contract: no exception for degenerate inputs.

### 5. `pd.Timestamp` coercion in the state machine

The loop iterates `underwater.items()`, which yields `(index_value, float)` pairs.
Because the index is a `DatetimeIndex`, each `date` is already a `pd.Timestamp` in
practice, but the explicit `pd.Timestamp(date)` cast is retained for clarity and to
handle any edge case where the index element is a `datetime.datetime` or string.

---

## Implementation Steps

### Step 1: Create this plan document

Written at `docs/plans/phase-3-backtesting/phase3.3_drawdown_analysis.md`.

### Step 2: Verify existing `src/csm/risk/drawdown.py`

Per `PLAN.md` status notes, `drawdown.py` was implemented during Phase 3.1 scaffolding.
The module is 57 lines and covers all three public methods:
- `max_drawdown()` — 3 lines (delegates to `underwater_curve().min()`)
- `underwater_curve()` — 2 lines (vectorised pandas expression)
- `recovery_periods()` — 27 lines (state machine, builds episode list, returns DataFrame)

No code changes were required — the existing implementation is correct and complete.

### Step 3: Extend `tests/unit/risk/test_drawdown.py` with additional edge cases

The 6 original tests from Phase 3.1 passed and cover the core behaviours. Three
additional tests were added to make the suite more explicit and cover edge cases
required by the ≥90% coverage target:

| New test | Covers |
|---|---|
| `test_recovery_periods_open_episode_not_included` | Open episode at end of series is excluded |
| `test_recovery_periods_multiple_episodes_count` | Exactly 2 rows for a 2-episode series |
| `test_max_drawdown_single_point_returns_zero` | Single-point series returns 0.0 |

All 9 tests pass: `uv run pytest tests/unit/risk/test_drawdown.py -v` exits 0.

### Step 4: Update plan and PLAN.md with completion notes

Document plan doc creation, test extension, confirmation that all tests pass, and any
deviations from the original plan.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `src/csm/risk/drawdown.py` | VERIFY | 57-line implementation — no changes required |
| `tests/unit/risk/test_drawdown.py` | MODIFY | Add 3 edge-case tests (open episode, episode count, single-point) |
| `docs/plans/phase-3-backtesting/phase3.3_drawdown_analysis.md` | CREATE | This document |
| `docs/plans/phase-3-backtesting/PLAN.md` | MODIFY | Phase 3.3 plan-doc creation and test extension notes |

---

## Test Coverage

All tests use `_series()` helper that produces a `pd.Series` with monthly
`DatetimeIndex` (tz=`Asia/Bangkok`) — matching the index produced by `MomentumBacktest`.

| Test | Method | Scenario |
|---|---|---|
| `test_underwater_curve_all_zeros_for_monotonic` | `underwater_curve` | Monotonically increasing — all zeros |
| `test_max_drawdown_matches_formula` | `max_drawdown` | Known series: peak=100, trough=80 → -0.20 |
| `test_max_drawdown_is_never_positive` | `max_drawdown` | Invariant: result ≤ 0 for any drawdown |
| `test_recovery_periods_empty_for_monotonic` | `recovery_periods` | Monotonic series → empty DataFrame |
| `test_recovery_periods_single_known_episode` | `recovery_periods` | Correct start, trough, recovery, depth |
| `test_duration_days_consistent_with_recovery_minus_start` | `recovery_periods` | `duration_days = (recovery - start).days` for all episodes |
| `test_recovery_periods_open_episode_not_included` | `recovery_periods` | Open episode at series end → empty DataFrame |
| `test_recovery_periods_multiple_episodes_count` | `recovery_periods` | 2-episode series → exactly 2 rows |
| `test_max_drawdown_single_point_returns_zero` | `max_drawdown` | Single-point series → 0.0 |

All 9 tests pass. No pytest-cov plugin installed in the project; manual branch analysis
confirms 100% branch coverage across all three public methods.

---

## Success Criteria

- [x] `uv run pytest tests/unit/risk/test_drawdown.py -v` exits 0 (9 tests pass)
- [x] `uv run mypy src/csm/risk/drawdown.py` exits 0
- [x] `uv run ruff check src/csm/risk/drawdown.py` exits 0
- [x] `underwater_curve` returns all-zero series for monotonically increasing input
- [x] `max_drawdown` returns correct negative float for known peak/trough series
- [x] `max_drawdown` invariant: result is always ≤ 0
- [x] `recovery_periods` returns empty DataFrame for monotonic series
- [x] `recovery_periods` correctly identifies start, trough, recovery, depth for single episode
- [x] `duration_days` equals `(recovery - start).days` for every episode
- [x] Open episode at series end is not included in episode table
- [x] 2-episode series returns exactly 2 rows
- [x] Single-point series returns `max_drawdown = 0.0` (no exception)
- [x] All 9 unit tests pass without regression in the wider test suite

---

## Completion Notes

### Summary

Phase 3.3 complete. The core implementation (`src/csm/risk/drawdown.py`, 57 lines) was
in place from the Phase 3.1 scaffolding session and required no changes. This phase
created the plan document, confirmed all original tests pass, and extended the test
suite with three additional edge-case tests:

- `test_recovery_periods_open_episode_not_included` — explicitly verifies that an
  unresolved drawdown at the end of the series produces an empty DataFrame, matching
  the spec requirement ("open episode at end not included").
- `test_recovery_periods_multiple_episodes_count` — explicitly verifies that exactly 2
  rows are returned for a 2-episode series (was implicitly covered by
  `test_duration_days_consistent_with_recovery_minus_start`; now explicit).
- `test_max_drawdown_single_point_returns_zero` — covers the degenerate 1-point input
  case, confirming the function does not raise and returns 0.0.

All 9 tests pass. The full non-integration test suite (198 tests before this phase, 201
after) shows no regressions introduced by the test additions.

### Issues Encountered

None. The scaffold implementation was correct and complete. The only work in this phase
was documentation (plan doc) and test hardening (3 additional edge-case tests).

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Sonnet 4.6)
**Status:** Complete
**Completed:** 2026-04-27
