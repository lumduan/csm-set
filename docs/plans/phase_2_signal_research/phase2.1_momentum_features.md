# Phase 2.1 - Momentum Features

**Feature:** Compute mom_12_1, mom_6_1, mom_3_1, mom_1_0 per symbol per rebalance date
**Branch:** `feature/phase-2-signal-research`
**Created:** 2026-04-24
**Status:** Complete — 2026-04-24
**Depends On:** Phase 1.5 (processed OHLCV in `data/processed/`)

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Function Signatures](#function-signatures)
6. [Implementation Steps](#implementation-steps)
7. [Test Plan](#test-plan)
8. [File Changes](#file-changes)
9. [Success Criteria](#success-criteria)
10. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 2.1 implements `MomentumFeatures`, the first building block of the signal-research layer.
It computes four raw momentum-return variants per symbol per rebalance date using only data
available on or before the rebalance date (strict no-look-ahead).

The four signals:

| Signal | Window | Skip | Formula |
| --- | --- | --- | --- |
| `mom_12_1` | 12 months | 1 month | `log(close[t-21] / close[t-252])` |
| `mom_6_1` | 6 months | 1 month | `log(close[t-21] / close[t-126])` |
| `mom_3_1` | 3 months | 1 month | `log(close[t-21] / close[t-63])` |
| `mom_1_0` | 1 month | none | `log(close[t] / close[t-21])` |

All offsets are in **trading days** (not calendar days) to handle SET public holidays.

### Parent Plan Reference

- `docs/plans/phase2_signal_research/PLAN.md`

### Key Deliverables

1. `src/csm/features/momentum.py` — `MomentumFeatures.compute()` with new per-symbol API
2. Updated `src/csm/features/pipeline.py` — calls `compute()` once per symbol for all rebalance dates
3. `tests/unit/features/test_momentum.py` — full test suite covering all PLAN test cases plus edge cases

---

## AI Prompt

The following prompt was used to generate this phase:

```text
🎯 Objective
Implement plan and code for Phase 2.1 - Momentum Features, following the specifications in
`docs/plans/phase2_signal_research/PLAN.md`. The plan must be documented as a markdown file at
`docs/plans/phase2_signal_research/phase2.1_momentum_features.md`, including the full prompt used.
After planning, implement the code, update progress in the main PLAN, and commit all changes.

📋 Context
- The project is in the `csm-set` repository, focusing on signal research for the SET market.
- Phase 2.1 is the first sub-phase of the signal research layer, responsible for computing momentum
  features (mom_12_1, mom_6_1, mom_3_1, mom_1_0) with strict no look-ahead bias.
- All requirements, deliverables, and test cases are detailed in
  `docs/plans/phase2_signal_research/PLAN.md`.
- The last implementation was in `docs/plans/phase2_signal_research/phase1.6-bulk-fetch-script.md`.
- The plan for this phase must be written before coding, saved as
  `docs/plans/phase2_signal_research/phase2.1_momentum_features.md`, and must include the prompt used.
- Upon completion, update progress in both the main PLAN and the phase-specific plan, noting any
  issues or test results.

🔧 Requirements
- Read and understand all requirements in `docs/plans/phase2_signal_research/PLAN.md`, focusing on
  Phase 2.1.
- Plan the implementation in detail before coding, covering:
  - Function signatures, input/output types, and logic for momentum feature computation.
  - Handling of look-ahead bias, NaN propagation, and trading day offsets.
  - Unit test design for all required test cases.
- Document the plan in markdown at
  `docs/plans/phase2_signal_research/phase2.1_momentum_features.md`, including the full prompt.
- Implement the code for `MomentumFeatures` in `src/csm/features/momentum.py` as specified.
- Write unit tests in `tests/unit/features/test_momentum.py` covering all required cases.
- Update `docs/plans/phase2_signal_research/PLAN.md` and
  `docs/plans/phase2_signal_research/phase2.1_momentum_features.md` with progress notes,
  completion status, and any issues encountered.
- All code must follow project standards: type safety, no look-ahead, async where needed, Pydantic
  models, and comprehensive docstrings.
- Commit all changes with a message referencing the phase and work completed.

📁 Code Context
- `docs/plans/phase2_signal_research/PLAN.md` (main requirements and checklist)
- `docs/plans/phase2_signal_research/phase1.6-bulk-fetch-script.md` (last implementation reference)
- `docs/plans/examples/phase1-sample.md` (plan format reference)
- Target plan file: `docs/plans/phase2_signal_research/phase2.1_momentum_features.md`
- Target implementation: `src/csm/features/momentum.py`
- Target tests: `tests/unit/features/test_momentum.py`

✅ Expected Output
- A detailed implementation plan for Phase 2.1 in
  `docs/plans/phase2_signal_research/phase2.1_momentum_features.md`, including the prompt.
- Implementation of `MomentumFeatures` in `src/csm/features/momentum.py` with all required features
  and no look-ahead bias.
- Unit tests in `tests/unit/features/test_momentum.py` covering all specified cases.
- Updated progress and notes in `docs/plans/phase2_signal_research/PLAN.md` and the phase-specific
  plan.
- All changes committed with a clear, standards-compliant commit message.
```

---

## Scope

### In Scope

- `MomentumFeatures.compute(close: pd.Series, rebalance_dates: pd.DatetimeIndex) -> pd.DataFrame`
  - Computes all four signals per rebalance date for a single symbol
  - Uses integer trading-day offsets (not calendar-day resampling)
  - Intermediate calculations in float64; output columns cast to float32
  - NaN when boundary price is missing, zero, or negative
  - Raises `ValueError` on duplicate timestamps in `close`
- Update `FeaturePipeline.build()` to call `compute()` once per symbol across all rebalance dates
- Replace old test for `compute(prices, formation_months, skip_months)` with new test suite

### Out of Scope

- Risk-adjusted features (Phase 2.2)
- Sector features (Phase 2.3)
- Pipeline winsorize/z-score (tested separately in Phase 2.4)
- IC analysis (Phase 2.6)

### API Change Summary

The existing `MomentumFeatures.compute(prices, formation_months, skip_months)` used a wide-matrix
approach with monthly resampling and simple returns. Phase 2.1 replaces it with:

```python
compute(close: pd.Series, rebalance_dates: pd.DatetimeIndex) -> pd.DataFrame
```

Key differences:

| Aspect | Old API | New API |
| --- | --- | --- |
| Input | Wide DataFrame (all symbols) | Single-symbol Series |
| Offsets | Monthly resample + iloc | Integer trading-day iloc |
| Return type | Simple return `(end/start) - 1` | Log return `log(end/start)` |
| Signals | mom_12_1, mom_6_1, mom_3_1 | + mom_1_0 (reversal) |
| Output | Cross-section snapshot Series | Time-series DataFrame per symbol |
| Pipeline usage | Called per rebalance date | Called once per symbol |

---

## Design Decisions

### Trading-Day Offsets (Not Calendar Days)

The SET observes Thai public holidays not on the standard pandas `BDay` calendar.
Resampling to monthly periods then using `iloc` introduces variable errors depending on how many
trading days the SET was open in a given month. Using exact trading-day integer offsets (counted
from the tail of the available price history) is robust because we count only actual trading days
that appear in the close Series.

Offset mapping:

- `t-21` ≈ 1 trading month (skip boundary for the three formation signals)
- `t-63` ≈ 3 trading months
- `t-126` ≈ 6 trading months
- `t-252` ≈ 12 trading months

### Non-Trading Rebalance Dates

If `t` is not a trading day (weekend, holiday), `hist = close.loc[close.index <= t]` returns all
trading-day closes up to the last trading day before `t`. The iloc offsets then count back from
that last trading day. The latest close used is always the last available trading close on or
before `t`, which is correct behavior for a rebalance scheduled on a non-trading day.

### Input Validation and Error Contract

| Input condition | Behavior |
| --- | --- |
| Unsorted `close` index | Sorted internally via `close.sort_index()` |
| Duplicate timestamps in `close` | Raise `ValueError` immediately |
| Non-positive price at boundary | Signal returns NaN (log is undefined for price ≤ 0) |
| Boundary price is NaN | Signal returns NaN (pandas NaN propagation) |
| `close` empty | All signals are NaN for every date |
| tz mismatch between `close.index` and `rebalance_dates` | Pandas `.loc` will raise a `TypeError`; documented as passthrough — callers must ensure consistent timezone |

### NaN Propagation

If the price at any boundary is missing or non-positive, return NaN for that signal on that date.
No back-fill across the boundary.

### No Look-Ahead Guarantee

Enforced by filtering before any iloc access:

```python
hist = close.loc[close.index <= t]
```

For the three formation signals, the most recent close accessed is `hist.iloc[-22]` (t-21 trading
days before the most recent close on or before `t`). For `mom_1_0` the end price is `hist.iloc[-1]`
(close at t). Prices after `t` in the Series are never visible.

### Log Returns, Float64 Intermediate, Float32 Output

Log returns are additive and better approximated as normally distributed in cross-sections.
All intermediate calculations use float64. The final DataFrame is cast to float32 to match the
panel schema defined in `PLAN.md`.

### Pipeline Efficiency: Once Per Symbol

The pipeline calls `compute(symbol_close, rebalance_dates)` once per symbol, getting back a full
time-series DataFrame. Results are then reshaped into the (date, symbol) MultiIndex panel.
This avoids the O(dates × symbols) overhead of calling once per date per symbol.

---

## Function Signatures

### `MomentumFeatures`

```python
class MomentumFeatures:
    """Compute cross-sectional momentum signals from a single-symbol close Series."""

    # (start_td, end_td): trading-day offsets before rebalance date t
    #   start_td: t - start_td is the start of the formation window
    #   end_td:   t - end_td is the end of the formation window (0 = close at t)
    _OFFSETS: dict[str, tuple[int, int]] = {
        "mom_12_1": (252, 21),
        "mom_6_1":  (126, 21),
        "mom_3_1":  (63,  21),
        "mom_1_0":  (21,   0),
    }

    def compute(
        self,
        close: pd.Series,
        rebalance_dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """Compute all four momentum signals for a single symbol across rebalance dates.

        Args:
            close: Daily close price Series for a single symbol. Must have a DatetimeIndex.
                   The index is sorted internally. Duplicate index values raise ValueError.
                   Non-positive or NaN prices at boundaries produce NaN signals.
                   The timezone of close.index must be compatible with rebalance_dates.
            rebalance_dates: Rebalance timestamps at which features are evaluated.
                   Dates that are not trading days use the last prior available close.

        Returns:
            DataFrame indexed by rebalance_dates with float32 columns
            [mom_12_1, mom_6_1, mom_3_1, mom_1_0]. NaN when insufficient history
            or a boundary price is invalid.

        Raises:
            ValueError: If close.index contains duplicate timestamps.
        """
```

### iloc Offset Derivation

For a history Series `hist` where `hist.iloc[-1]` is the close on or before `t`:

```text
price at t        = hist.iloc[-1]         (needs len >= 1)
price at t-21     = hist.iloc[-22]        (needs len >= 22)
price at t-63     = hist.iloc[-64]        (needs len >= 64)
price at t-126    = hist.iloc[-127]       (needs len >= 127)
price at t-252    = hist.iloc[-253]       (needs len >= 253)
```

Minimum history required per signal:

| Signal | Prices accessed | Minimum len(hist) |
| --- | --- | --- |
| `mom_12_1` | hist.iloc[-22], hist.iloc[-253] | 253 |
| `mom_6_1` | hist.iloc[-22], hist.iloc[-127] | 127 |
| `mom_3_1` | hist.iloc[-22], hist.iloc[-64] | 64 |
| `mom_1_0` | hist.iloc[-1], hist.iloc[-22] | 22 |

---

## Implementation Steps

1. **Rewrite `momentum.py`**
   - Remove old `compute(prices, formation_months, skip_months)` and `compute_multi(prices)`
   - Add `_OFFSETS` class attribute
   - Implement `compute(close, rebalance_dates)`:
     - Validate no duplicate index: `if close.index.duplicated().any(): raise ValueError(...)`
     - Sort: `close = close.sort_index()`
     - For each `t` in `rebalance_dates`: `hist = close.loc[close.index <= t]`
     - For each signal: check `len(hist) >= start_td + 1`; get prices via iloc; NaN if price ≤ 0
     - Compute `np.log(end_price / start_price)` in float64; collect rows
     - Cast final DataFrame to float32
   - Update `__all__`

2. **Update `pipeline.py`**
   - For each symbol in the close matrix, call `self._momentum.compute(symbol_close, rebalance_dates_index)` once
   - Collect per-symbol DataFrames; stack into (date, symbol) MultiIndex

3. **Rewrite `test_momentum.py`**
   - Implement all 9 test cases from the Test Plan below

---

## Test Plan

### Test Case 1 — mom_12_1 matches manual pandas calculation

Build a deterministic 300-day close Series. `t = close.index[-1]`.

```python
hist = close
expected = np.log(float(hist.iloc[-22]) / float(hist.iloc[-253]))
result = MomentumFeatures().compute(close, pd.DatetimeIndex([t]))
assert abs(float(result.at[t, "mom_12_1"]) - expected) < 1e-5
```

### Test Case 2 — all four signals match reference calculations

Same 300-day series. Verify all signals:

```python
assert abs(result["mom_6_1"]  - np.log(hist.iloc[-22]  / hist.iloc[-127])) < 1e-5
assert abs(result["mom_3_1"]  - np.log(hist.iloc[-22]  / hist.iloc[-64]))  < 1e-5
assert abs(result["mom_1_0"]  - np.log(hist.iloc[-1]   / hist.iloc[-22]))  < 1e-5
```

### Test Case 3 — no look-ahead bias

**Scenario A — mutate after `t`:**
Build 300-day series; `t = close.index[279]`. Record all four signals. Mutate prices at indices
after `t` (days 280+). Re-run. Assert all four signals are unchanged (those dates are outside
`hist = close.loc[close.index <= t]`).

**Scenario B — mutate `t-20 ... t` (inside `mom_1_0` window, outside formation window):**
Starting from the original series, mutate prices at `close.index[259:280]` (`t-20 ... t`), while
leaving `close.index[258]` (`t-21`) unchanged. Re-run `compute`. Assert:

- `mom_12_1`, `mom_6_1`, `mom_3_1` are **unchanged** (their end price is at `t-21`)
- `mom_1_0` **does change** (its formation window is `[t-21, t]`)

### Test Case 4 — NaN propagation when history shorter than lookback window

Close Series with exactly 50 prices. `rebalance_date = close.index[-1]`:

```text
mom_12_1 -> NaN  (needs 253, have 50)
mom_6_1  -> NaN  (needs 127, have 50)
mom_3_1  -> NaN  (needs 64, have 50)
mom_1_0  -> valid float (needs 22, have 50)
```

### Test Case 5 — rebalance date falls on a non-trading day

Build a 300-day trading-day Series (freq="B"). Find a Saturday after the last trading day.
Assert `compute(close, [saturday])["mom_12_1"]` equals `compute(close, [last_friday])["mom_12_1"]`.

### Test Case 6 — boundary price is NaN

300-day series; insert `np.nan` at `iloc[-22]`. Assert `mom_12_1`, `mom_6_1`, `mom_3_1` and
`mom_1_0` are all NaN (both formation end and `mom_1_0` start are at that position).

### Test Case 7 — boundary price is non-positive

300-day series; set `iloc[-22] = 0.0`. Assert all four signals are NaN.

### Test Case 8 — unsorted input is handled

Pass the close Series in reverse. Assert the result equals the result from the forward-sorted series.

### Test Case 9 — multiple rebalance dates preserve order and columns

Pass 3 ascending rebalance dates. Assert result has 3 rows matching the order of the input dates
and columns are exactly `["mom_12_1", "mom_6_1", "mom_3_1", "mom_1_0"]` in that order.

**Also:** pass a duplicate index close Series; assert `ValueError` is raised.

---

## File Changes

| File | Action | Notes |
| --- | --- | --- |
| `src/csm/features/momentum.py` | Rewrite | New per-symbol API, log returns, float32 |
| `src/csm/features/pipeline.py` | Update | Call compute() once per symbol for all dates |
| `tests/unit/features/test_momentum.py` | Rewrite | All 9 test cases above |
| `docs/plans/phase2_signal_research/PLAN.md` | Update | Mark Phase 2.1 checklist items |
| `docs/plans/phase2_signal_research/phase2.1_momentum_features.md` | Create | This file |

---

## Success Criteria

- [x] `uv run pytest tests/unit/features/ -v` exits 0 with all new tests passing
- [x] `uv run mypy src/csm/features/momentum.py` exits 0
- [x] `uv run ruff check src/csm/features/momentum.py` exits 0
- [x] All 9 test cases implemented and passing (16 total including subtests)
- [x] No test uses `formation_months` / `skip_months` (old API fully replaced)
- [x] Pipeline test (`test_pipeline_z_scores_cross_sectionally`) still passes

---

## Completion Notes

All deliverables completed on 2026-04-24.

- 16 tests pass (`uv run pytest tests/unit/features/ -v`)
- `uv run mypy` and `uv run ruff check` both exit 0 on changed files
- `test_pipeline_z_scores_cross_sectionally` still passes after pipeline update
- API replaced from wide-matrix + monthly resample to per-symbol + trading-day offsets
- Log returns and float32 output as specified
- No look-ahead verified by two test scenarios (mutation after t; mutation in skip window)
