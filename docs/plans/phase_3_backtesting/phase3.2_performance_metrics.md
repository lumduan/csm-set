# Phase 3.2 — Performance Metrics

**Feature:** Annualised Performance Metrics for Backtest Results
**Branch:** `feature/phase-3-backtesting`
**Created:** 2026-04-27
**Status:** Complete
**Completed:** 2026-04-27
**Depends On:** Phase 3.1 (Backtest Engine — Complete)

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

Phase 3.2 delivers `PerformanceMetrics` — a class that computes the full suite of
annualised risk/return statistics from a backtest equity curve. It is the final
step in `MomentumBacktest.run()` before `BacktestResult` is assembled: after the
equity curve is built the backtest calls `PerformanceMetrics.summary()` to populate
`BacktestResult.metrics`.

All outputs are public-safe (no raw OHLCV prices). The metrics dict is the
primary artefact persisted to `results/backtest/summary.json` for the Phase 7
public Docker image and used in the Phase 3.4 sign-off notebook.

### Parent Plan Reference

- `docs/plans/phase-3-backtesting/PLAN.md`

### Key Deliverables

1. **`src/csm/risk/metrics.py`** — `PerformanceMetrics.summary()` with 8 base metrics
   plus optional alpha/beta/IR when a benchmark series is provided.
2. **`tests/unit/risk/test_metrics.py`** — 9 unit tests covering all metrics, edge
   cases, and the benchmark path.
3. **Bug fix** — `pd.concat(..., sort=False)` to silence the pandas
   `Pandas4Warning` about sort-on-concat deprecation.

---

## AI Prompt

The following prompt was used to generate this phase:

```
🎯 Objective
Create a comprehensive implementation plan and execution workflow for Phase 3.2 —
Performance Metrics in the SET momentum backtesting project. The plan must be written
as a markdown file at `docs/plans/phase-3-backtesting/phase3.2_performance_metrics.md`
(following the format in `docs/plans/examples/phase1-sample.md`), and must include the
full prompt used for this task. After planning, implement the phase as specified, update
all relevant documentation with progress notes, and commit the changes.

📋 Context
- The project is a multi-phase research and production pipeline for SET market momentum
  strategies.
- Phase 3.2 focuses on implementing robust, public-safe performance metrics for backtest
  results, as described in `docs/plans/phase-3-backtesting/PLAN.md`.
- The previous phase (3.1) delivered a vectorized walk-forward backtest engine and full
  unit test coverage, documented in
  `docs/plans/phase-3-backtesting/phase3.1_backtest_engine.md`.
- All planning and implementation steps must be documented, and progress must be updated
  in the plan files.
- The plan markdown must include the prompt used for this task.

🔧 Requirements
- Carefully read and understand `docs/plans/phase-3-backtesting/PLAN.md`, focusing on
  Phase 3.2 — Performance Metrics, and review the previous phase's plan at
  `docs/plans/phase-3-backtesting/phase3.1_backtest_engine.md`.
- Before coding, create a detailed plan for Phase 3.2 as a markdown file at
  `docs/plans/phase-3-backtesting/phase3.2_performance_metrics.md`, following the format
  in `docs/plans/examples/phase1-sample.md`. The plan must include the full prompt used
  for this job.
- Only begin implementation after the plan is complete and committed.
- Implement the performance metrics module according to the requirements and architecture
  in the plan and master plan.
- After implementation, update `docs/plans/phase-3-backtesting/PLAN.md` and
  `docs/plans/phase-3-backtesting/phase3.2_performance_metrics.md` with progress notes,
  completion dates, and any issues encountered.
- All code must follow project architectural standards: type safety, async/await patterns,
  Pydantic validation, comprehensive error handling, and public-safe outputs.
- All new features must have unit tests with ≥90% coverage, including edge cases and error
  conditions.
- Commit all changes with a clear, standards-compliant commit message.

📁 Code Context
- `docs/plans/phase-3-backtesting/PLAN.md` (master plan, requirements, architecture)
- `docs/plans/phase-3-backtesting/phase3.1_backtest_engine.md` (previous phase plan and
  implementation context)
- `docs/plans/examples/phase1-sample.md` (plan markdown format reference)
- Target plan file: `docs/plans/phase-3-backtesting/phase3.2_performance_metrics.md`
- Implementation files: as specified in the plan (likely `src/csm/risk/metrics.py`,
  related test and model files)
- Documentation files: as above

✅ Expected Output
- A new plan markdown file at
  `docs/plans/phase-3-backtesting/phase3.2_performance_metrics.md` detailing the
  approach for Phase 3.2, including the full prompt.
- Implementation of the performance metrics module as specified in the plan.
- Updated progress notes in `docs/plans/phase-3-backtesting/PLAN.md` and
  `docs/plans/phase-3-backtesting/phase3.2_performance_metrics.md`.
- All changes committed with a clear, standards-compliant commit message.
```

---

## Scope

### In Scope (Phase 3.2)

| Component | Description | Status |
|---|---|---|
| `PerformanceMetrics.summary()` | 8 base metrics from equity curve | Complete |
| CAGR | `(end/start)^(1/years) - 1` | Complete |
| Sharpe ratio | `(annual_return - rf) / annual_volatility`; `rf = 0.02` from `constants.py` | Complete |
| Sortino ratio | `(annual_return - rf) / downside_volatility` | Complete |
| Calmar ratio | `cagr / abs(max_drawdown)`; delegates to `DrawdownAnalyzer` | Complete |
| Max drawdown | Delegated to `DrawdownAnalyzer.max_drawdown()` | Complete |
| Win rate | Fraction of monthly periods with positive return | Complete |
| Average monthly return | Mean of monthly return series | Complete |
| Annualised volatility | `std(ddof=0) * sqrt(12)` | Complete |
| Alpha / Beta / IR | Only when `benchmark` is provided | Complete |
| `tests/unit/risk/test_metrics.py` | 9 unit tests — all metrics + edge cases + benchmark path | Complete |
| Pandas warning fix | `pd.concat(..., sort=False)` to silence `Pandas4Warning` | Complete |

### Out of Scope (Phase 3.2)

- `DrawdownAnalyzer` implementation (Phase 3.3 — complete at scaffold time)
- `BacktestResult` Pydantic model (Phase 3.1 — `backtest.py`)
- Notebook charts and sign-off (Phase 3.4)
- Bootstrap confidence intervals around Sharpe (Future Enhancement)
- Regime-conditional metrics (Phase 4)

---

## Design Decisions

### 1. `ddof=0` for all variance calculations

The master plan specifies that beta uses `cov(portfolio, benchmark) / var(benchmark)`.
The initial scaffold used `aligned.cov()` (pandas default `ddof=1`) for covariance
but `aligned["benchmark"].var(ddof=0)` for variance — an inconsistency that caused
β ≠ 1.0 when portfolio = benchmark.

**Fix:** All variance and covariance computations use `ddof=0` (population statistics)
for internal consistency. This matches numpy convention and ensures β = 1.0 exactly
when the two series are identical, which is a clean regression test.

### 2. Annualisation factor is 12 (monthly periods)

The equity curve produced by `MomentumBacktest` is monthly. `volatility = std * √12`,
`annual_return = mean * 12`, `information_ratio = mean_excess * 12 / tracking_error`.
If daily data is ever used, this factor must be updated; it is not abstracted to a
constant because it is a property of the input data frequency, not a calibration
parameter.

### 3. Risk-free rate from `constants.py`

`RISK_FREE_RATE_ANNUAL = 0.02` is imported from `csm.config.constants` so that
changing the assumption requires editing one file. This approximates THOR (Thai
overnight rate) over the backtest period.

### 4. Empty equity curve returns all-zero dict — no exception

If the equity curve has ≤ 1 point, `pct_change().dropna()` is empty. Rather than
raising, `summary()` returns an all-zero dict. This makes the function safe to call
even during partially-initialised backtest state and avoids cascading errors in the
notebook when data is unavailable.

### 5. Alpha/beta present only when benchmark is provided

`alpha`, `beta`, and `information_ratio` are written into the metrics dict only when
`benchmark is not None and not benchmark.empty`. This keeps the base metrics dict
deterministic (same 8 keys regardless of call site) and avoids `KeyError` in
downstream code that accesses metrics without a benchmark.

### 6. `pd.concat` with `sort=False`

Pandas 4.x deprecates sorting on concat when all indexes are `DatetimeIndex`.
The `pd.concat([portfolio, benchmark], axis=1)` call aligns on the date index — no
reordering is desired. Adding `sort=False` silences the `Pandas4Warning` and is
semantically correct.

---

## Implementation Steps

### Step 1: Create this plan document

Written at `docs/plans/phase-3-backtesting/phase3.2_performance_metrics.md`.

### Step 2: Verify existing `src/csm/risk/metrics.py`

Per `PLAN.md` status notes, `metrics.py` was implemented and the `ddof` bug was
fixed during Phase 3.1. The module is 103 lines and covers all 8 base metrics plus
the optional benchmark path.

### Step 3: Verify and extend `tests/unit/risk/test_metrics.py`

Per `PLAN.md` status notes, 9 tests were written covering:
- `test_sharpe_matches_manual_calculation` — original test from scaffold
- `test_cagr_matches_formula` — `(end/start)^(1/years) - 1` identity
- `test_sortino_higher_than_sharpe_with_small_downside_vol` — Sortino > Sharpe when
  positive returns dominate
- `test_max_drawdown_is_negative` — invariant: `max_drawdown ≤ 0`
- `test_win_rate_three_of_four_positive` — exact `0.75` win rate
- `test_empty_equity_curve_returns_zero_dict` — all zeros for 1-point series
- `test_alpha_beta_absent_without_benchmark` — 3 keys absent without benchmark
- `test_alpha_beta_present_with_benchmark` — 3 keys present with benchmark
- `test_beta_equals_one_for_identical_series` — β = 1.0 identity check

### Step 4: Fix `pd.concat` pandas warning

Add `sort=False` to the `pd.concat` call in `summary()` at line 75 of `metrics.py`
to silence the `Pandas4Warning` about default sort behaviour changing in Pandas 4.

### Step 5: Update plan and PLAN.md with completion notes

Document issues, confirmation that all tests pass, and any deviations from the plan.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `src/csm/risk/metrics.py` | MODIFY | Add `sort=False` to `pd.concat` call (line 75) |
| `tests/unit/risk/test_metrics.py` | VERIFY | 9 unit tests — already complete from Phase 3.1 |
| `docs/plans/phase-3-backtesting/phase3.2_performance_metrics.md` | CREATE | This document |
| `docs/plans/phase-3-backtesting/PLAN.md` | MODIFY | Phase 3.2 plan-doc creation note |

---

## Test Coverage

All tests use `_monthly_equity()` helper that produces a `pd.Series` with monthly
`DatetimeIndex` (tz=`Asia/Bangkok`) — matching the index produced by `MomentumBacktest`.

| Test | Metric(s) verified |
|---|---|
| `test_sharpe_matches_manual_calculation` | `sharpe` |
| `test_cagr_matches_formula` | `cagr` |
| `test_sortino_higher_than_sharpe_with_small_downside_vol` | `sortino > sharpe` |
| `test_max_drawdown_is_negative` | `max_drawdown ≤ 0` |
| `test_win_rate_three_of_four_positive` | `win_rate` |
| `test_empty_equity_curve_returns_zero_dict` | All 8 base keys = 0.0 |
| `test_alpha_beta_absent_without_benchmark` | Key absence |
| `test_alpha_beta_present_with_benchmark` | `alpha`, `beta`, `information_ratio` present |
| `test_beta_equals_one_for_identical_series` | `beta ≈ 1.0` |

---

## Success Criteria

- [x] `uv run pytest tests/unit/risk/test_metrics.py -v` exits 0 (9 tests pass)
- [x] `uv run mypy src/csm/risk/metrics.py` exits 0
- [x] `uv run ruff check src/csm/risk/metrics.py` exits 0
- [x] CAGR matches `(end/start)^(1/years) - 1` for a known 12-period series
- [x] Sharpe matches manual formula
- [x] `max_drawdown ≤ 0` invariant holds
- [x] `win_rate = 0.75` for 3-of-4 positive series
- [x] All-zero dict returned for 1-point equity curve (no returns)
- [x] `alpha`, `beta`, `information_ratio` absent without benchmark
- [x] `beta ≈ 1.0` when portfolio = benchmark (ddof consistency fix)
- [x] No `Pandas4Warning` in test output (`sort=False` fix)
- [x] All 8 base metric keys present in every non-empty result

---

## Completion Notes

### Summary

Phase 3.2 complete. The core implementation (`src/csm/risk/metrics.py`, 103 lines)
and full unit test suite (`tests/unit/risk/test_metrics.py`, 9 tests) were in place
from the Phase 3.1 session. This phase created the plan document, confirmed all tests
pass, and applied one minor fix: `pd.concat(..., sort=False)` silences the
`Pandas4Warning` that appeared in test output when aligning portfolio and benchmark
series on a `DatetimeIndex`.

### Issues Encountered

1. **`ddof` inconsistency in beta** — The initial `cov(ddof=1)` / `var(ddof=0)`
   mismatch caused β ≠ 1.0 when portfolio = benchmark. Fixed in Phase 3.1 by
   switching to `cov(ddof=0)` throughout. The `test_beta_equals_one_for_identical_series`
   test guards this invariant.

2. **`Pandas4Warning` on `pd.concat`** — `pd.concat([portfolio, benchmark], axis=1)`
   without `sort` triggers a deprecation warning in pandas ≥ 2.x when all inputs are
   `DatetimeIndex`. Fixed by adding `sort=False`, which is the semantically correct
   default (no reordering of aligned date indexes is desired).

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Sonnet 4.6)
**Status:** Complete
**Completed:** 2026-04-27
