# Phase 2.3 - Sector Features

**Feature:** Compute sector_rel_strength per symbol per rebalance date
**Branch:** `feature/phase-2-signal-research`
**Created:** 2026-04-25
**Status:** Complete — 2026-04-25
**Depends On:** Phase 2.1 (MomentumFeatures API pattern), Phase 1.5 (processed OHLCV)

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

Phase 2.3 implements `SectorFeatures`, the third building block of the signal-research layer.
It computes one sector-relative momentum feature per symbol per rebalance date using only data
available strictly on or before `t-21` trading days (strict no-look-ahead).

The signal:

| Signal | Formula | Description |
| --- | --- | --- |
| `sector_rel_strength` | `mom_12_1(symbol) - mom_12_1(sector_index)` | Symbol 12M log return minus sector-index 12M log return, both with a 1M skip |

The **mom_12_1** formula is identical to Phase 2.1: `log(hist.iloc[-22] / hist.iloc[-253])`.
Both the symbol and the sector index require `min_hist = 253` trading days in
`close.loc[<= t]` to compute this signal.

### Parent Plan Reference

- `docs/plans/phase2_signal_research/PLAN.md`

### Key Deliverables

1. `src/csm/features/sector.py` — `SectorFeatures.compute()` rewritten with per-symbol API,
   replacing the old wide-matrix `relative_strength()` implementation
2. `tests/unit/features/test_sector.py` — new test suite covering all PLAN test cases

---

## AI Prompt

The following prompt was used to generate this phase:

```text
🎯 Objective
Implement plan and execution workflow for Phase 2.3 - Sector Features in the csm-set project,
following the established planning-before-coding methodology. The plan must be saved as a markdown
file at docs/plans/phase2_signal_research/phase2.3_sector_features.md (including the full prompt
used), and all progress must be tracked in both the main PLAN and the phase-specific plan. After
planning, implement the code, write tests, and update documentation and progress notes accordingly.

📋 Context
- The csm-set repository is a modular signal research pipeline for the SET market, with each phase
  building on the previous.
- Phase 2.3 focuses on implementing sector-based features, as detailed in
  docs/plans/phase2_signal_research/PLAN.md.
- The previous phase (2.2 - Risk-Adjusted Features) is fully implemented and documented in
  docs/plans/phase2_signal_research/phase2.2_risk_adjusted_features.md, serving as a reference
  for planning, implementation, and documentation standards.
- The workflow requires that a detailed plan be written and committed before any code is
  implemented, and that all progress and issues are documented in both the main PLAN and the
  phase-specific plan.

🔧 Requirements
- Carefully read and understand all requirements in docs/plans/phase2_signal_research/PLAN.md,
  focusing specifically on the 2.3 Sector Features section.
- Review the previous phase's plan and implementation in
  docs/plans/phase2_signal_research/phase2.2_risk_adjusted_features.md to ensure interface and
  documentation consistency.
- Write a detailed implementation plan for Phase 2.3, covering:
  - Function signatures, input/output types, and logic for sector feature computation.
  - Handling of sector classification, NaN propagation, and trading day alignment.
  - Unit test design for all required test cases.
  - Any dependencies or integration points with previous features.
- Save the plan as docs/plans/phase2_signal_research/phase2.3_sector_features.md, including the
  full prompt used, and following the format in docs/plans/examples/phase1-sample.md.
- Only begin implementation after the plan is complete and committed.
- Implement the code for sector features in the appropriate module
  (e.g., src/csm/features/sector.py), following all project standards for type safety, async
  patterns, and documentation.
- Write unit tests in tests/unit/features/test_sector.py covering all required cases.
- Update docs/plans/phase2_signal_research/PLAN.md and
  docs/plans/phase2_signal_research/phase2.3_sector_features.md with progress notes, completion
  status, and any issues encountered.
- Commit all changes with a clear, standards-compliant commit message.

📁 Code Context
- docs/plans/phase2_signal_research/PLAN.md (requirements and checklist for Phase 2.3)
- docs/plans/phase2_signal_research/phase2.2_risk_adjusted_features.md (reference for planning
  and implementation standards)
- docs/plans/examples/phase1-sample.md (reference for plan markdown format)
- Target plan file: docs/plans/phase2_signal_research/phase2.3_sector_features.md
- Target implementation: src/csm/features/sector.py
- Target tests: tests/unit/features/test_sector.py

✅ Expected Output
- A detailed implementation plan for Phase 2.3, saved as
  docs/plans/phase2_signal_research/phase2.3_sector_features.md, including the full prompt and
  following the required format.
- Implementation of sector features in src/csm/features/sector.py, fully type-safe and documented.
- Comprehensive unit tests in tests/unit/features/test_sector.py.
- Updated progress notes and completion status in both
  docs/plans/phase2_signal_research/PLAN.md and
  docs/plans/phase2_signal_research/phase2.3_sector_features.md.
- All changes committed with a clear, standards-compliant commit message.
```

---

## Scope

### In Scope

- `SectorFeatures.compute(symbol_close, sector_closes, symbol_sector, rebalance_dates) -> pd.DataFrame`
  - One signal: `sector_rel_strength`
  - Per-symbol, time-series API (same pattern as Phase 2.1 `MomentumFeatures.compute`)
  - Integer trading-day iloc offsets — no calendar resampling
  - Intermediate float64; output cast to float32
  - NaN when symbol history < 253, sector history < 253, or sector code not in `sector_closes`
  - `TypeError` on non-DatetimeIndex inputs (symbol_close, sector series, rebalance_dates)
  - `ValueError` on duplicate timestamps in symbol_close or sector series
- Full replacement of old wide-matrix `SectorFeatures.relative_strength()` API

### Out of Scope

- Sector index construction from individual stock closes (pipeline's responsibility in Phase 2.4)
- `pipeline.py` integration (deferred to Phase 2.4 — the caller needs universe-filtered sector closes)
- Pipeline winsorize/z-score (Phase 2.4)
- IC analysis (Phase 2.6)

### Old API Audit

The current `sector.py` exposes `relative_strength(prices: pd.DataFrame, sector_map: dict[str, str]) -> pd.DataFrame`,
a wide-matrix API using 63-day simple returns. This method is not called from `pipeline.py`
(confirmed by grep — not present in pipeline imports). It is fully replaced in this phase.

---

## Design Decisions

### Signal Window: Same as mom_12_1

`sector_rel_strength` uses exactly the same lookback window as `mom_12_1` from Phase 2.1:

```text
hist = close.loc[close.index <= t]
sector_hist = sector_close.loc[sector_close.index <= t]

mom_12_1(symbol) = log(hist.iloc[-22] / hist.iloc[-253])
mom_12_1(sector) = log(sector_hist.iloc[-22] / sector_hist.iloc[-253])
sector_rel_strength = mom_12_1(symbol) - mom_12_1(sector)
```

Minimum history required: `hist` and `sector_hist` must each have at least `_MIN_HIST = 253`
elements on or before date `t`. 253 prices produce a valid `iloc[-22]` (price at t-21) and
a valid `iloc[-253]` (price at t-252).

### Sector Close Input: dict[str, pd.Series]

The caller passes a dict mapping sector codes (e.g., `"AGRI"`, `"BANK"`) to pre-computed sector
close Series. The sector index can be an equal-weight average of in-universe peers or any other
aggregation — `SectorFeatures` does not compute it. This design keeps the class
single-responsibility and allows the pipeline to build the sector index using whatever universe
filter it deems appropriate.

`symbol_sector` is the sector code for the symbol being computed. If `symbol_sector` is not a
key in `sector_closes`, the output is NaN for all rebalance dates (no fallback to market index).

### No Cross-Alignment

Unlike `residual_momentum` in Phase 2.2, the sector signal does **not** require date alignment
between symbol and sector series. Both are sliced with `iloc[-22]` and `iloc[-253]` independently,
so the sector index can have different trading dates (e.g., if it is computed from a different
subset of stocks). This avoids over-engineering for a straightforward difference of log-returns.

### No Look-Ahead Guarantee

Enforced by:

```python
hist         = close.loc[close.index <= t]
sector_hist  = sector_close.loc[sector_close.index <= t]
```

The most recent data accessed is `hist.iloc[-22]` and `sector_hist.iloc[-22]`, corresponding to
the close at `t-21` trading days. Prices in the skip region (`t-20` through `t`) are never read.

---

## Function Signatures

### `SectorFeatures`

```python
_MIN_HIST: int = 253  # 253 prices → valid iloc[-22] and iloc[-253]

_SIGNAL_NAMES: list[str] = ["sector_rel_strength"]


class SectorFeatures:
    """Compute sector-relative momentum features."""

    def compute(
        self,
        symbol_close: pd.Series,
        sector_closes: dict[str, pd.Series],
        symbol_sector: str,
        rebalance_dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """Compute sector_rel_strength per rebalance date.

        sector_rel_strength = mom_12_1(symbol) - mom_12_1(sector_index)
        where mom_12_1 = log(price at t-21 / price at t-252).

        Args:
            symbol_close: Daily close price Series for a single symbol.
                          DatetimeIndex required. Sorted internally.
                          Duplicate timestamps raise ValueError.
            sector_closes: Mapping from sector code to daily close Series
                           of the sector index. The Series for symbol_sector
                           must have a DatetimeIndex. Duplicates raise ValueError.
            symbol_sector: Sector code for this symbol (e.g. "BANK"). If not
                           a key in sector_closes, all rows are NaN.
            rebalance_dates: Rebalance DatetimeIndex. Non-trading dates use
                   the last available close on or before that date.
                   Must be a DatetimeIndex or TypeError is raised.

        Returns:
            DataFrame indexed by rebalance_dates, float32 column
            [sector_rel_strength]. NaN when:
              - len(hist) < 253 (symbol history too short)
              - symbol_sector not in sector_closes
              - len(sector_hist) < 253 (sector history too short)
              - any boundary price is non-positive or NaN

        Raises:
            TypeError:  If symbol_close.index, rebalance_dates, or the sector
                        Series index is not a DatetimeIndex.
            ValueError: If symbol_close.index or a sector Series index has
                        duplicate timestamps.
        """
```

### Module-Private Helpers

```python
def _mom_12_1(hist: pd.Series) -> float:
    """log(hist.iloc[-22] / hist.iloc[-253]). Returns NaN if any boundary price <= 0 or NaN."""
```

---

## Implementation Steps

1. **Rewrite `sector.py`**
   - Remove `relative_strength(prices, sector_map)` method
   - Add module constant `_MIN_HIST = 253`
   - Add private helper `_mom_12_1(hist)` returning `float`
   - Implement `compute(symbol_close, sector_closes, symbol_sector, rebalance_dates)`:
     - Validate `DatetimeIndex` type for `symbol_close` and `rebalance_dates`
     - Validate no duplicate timestamps for `symbol_close`
     - If `symbol_sector` not in `sector_closes`: all rows NaN, return early
     - Validate `DatetimeIndex` and no duplicates for the relevant sector Series
     - Sort `symbol_close` and the relevant sector Series
     - For each `t` in `rebalance_dates`:
       - `hist = symbol_close.loc[symbol_close.index <= t]`
       - `sector_hist = sector_close.loc[sector_close.index <= t]`
       - If `len(hist) < _MIN_HIST` or `len(sector_hist) < _MIN_HIST`: NaN, continue
       - `sym_mom = _mom_12_1(hist)`
       - `sec_mom = _mom_12_1(sector_hist)`
       - `sector_rel_strength = sym_mom - sec_mom` (NaN if either is NaN)
     - Build DataFrame, cast to float32
   - Update `__all__`

2. **Create `tests/unit/features/test_sector.py`**
   - All test cases from the Test Plan below

---

## Test Plan

### Fixtures

```python
_TZ = "Asia/Bangkok"

def _make_close(n: int = 300, seed: int = 42, tz: str = _TZ) -> pd.Series:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2021-01-04", periods=n, freq="B", tz=tz)
    return pd.Series(100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, n))),
                     index=dates, name="SYM")

def _make_sector(n: int = 300, seed: int = 99, tz: str = _TZ) -> pd.Series:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2021-01-04", periods=n, freq="B", tz=tz)
    return pd.Series(1000.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n))),
                     index=dates, name="BANK_IDX")
```

Use `n=300` to comfortably exceed `_MIN_HIST = 253`.

### Test Case 1 — output schema (shape, columns, dtype)

```python
def test_output_schema():
    close = _make_close()
    sector = _make_sector()
    t = close.index[-1]
    result = SectorFeatures().compute(close, {"BANK": sector}, "BANK", pd.DatetimeIndex([t]))
    assert list(result.columns) == ["sector_rel_strength"]
    assert result.dtypes["sector_rel_strength"] == np.float32
    assert result.index[0] == t
```

### Test Case 2 — sector_rel_strength == 0 when symbol equals sector

```python
def test_zero_when_symbol_equals_sector():
    close = _make_close()
    t = close.index[-1]
    result = SectorFeatures().compute(close, {"BANK": close}, "BANK", pd.DatetimeIndex([t]))
    assert abs(float(result.at[t, "sector_rel_strength"])) < 1e-5
```

### Test Case 3 — positive when symbol outperforms sector

Symbol and sector are built from deterministic log-return arrays (no random noise) so that
the 12-1M log return of the symbol is guaranteed to exceed the sector's. Multiplying a price
series by a constant does not change log returns — use distinct drift rates instead.

```python
def test_positive_when_symbol_outperforms():
    n = 300
    dates = pd.date_range("2021-01-04", periods=n, freq="B", tz=_TZ)
    # Deterministic: symbol drifts up, sector drifts flat
    sym_rets = np.full(n, 0.003)    # +0.3%/day
    sec_rets = np.full(n, 0.0)      # flat
    symbol = pd.Series(100.0 * np.exp(np.cumsum(sym_rets)), index=dates, name="SYM")
    sector = pd.Series(100.0 * np.exp(np.cumsum(sec_rets)), index=dates, name="SEC")
    t = dates[-1]
    result = SectorFeatures().compute(symbol, {"AGRI": sector}, "AGRI", pd.DatetimeIndex([t]))
    assert float(result.at[t, "sector_rel_strength"]) > 0
```

### Test Case 4 — negative when symbol underperforms sector

```python
def test_negative_when_symbol_underperforms():
    n = 300
    dates = pd.date_range("2021-01-04", periods=n, freq="B", tz=_TZ)
    # Deterministic: symbol drifts down, sector drifts up
    sym_rets = np.full(n, -0.003)   # -0.3%/day
    sec_rets = np.full(n, 0.003)    # +0.3%/day
    symbol = pd.Series(100.0 * np.exp(np.cumsum(sym_rets)), index=dates, name="SYM")
    sector = pd.Series(100.0 * np.exp(np.cumsum(sec_rets)), index=dates, name="SEC")
    t = dates[-1]
    result = SectorFeatures().compute(symbol, {"FOOD": sector}, "FOOD", pd.DatetimeIndex([t]))
    assert float(result.at[t, "sector_rel_strength"]) < 0
```

### Test Case 5 — NaN when sector code is missing from sector_closes

```python
def test_nan_when_sector_missing():
    close = _make_close()
    t = close.index[-1]
    result = SectorFeatures().compute(close, {}, "BANK", pd.DatetimeIndex([t]))
    assert np.isnan(float(result.at[t, "sector_rel_strength"]))
```

### Test Case 6 — NaN when symbol history < _MIN_HIST

```python
def test_nan_when_symbol_history_too_short():
    close = _make_close(200)   # only 200 days, need 253
    sector = _make_sector(300)
    t = close.index[-1]
    result = SectorFeatures().compute(close, {"BANK": sector}, "BANK", pd.DatetimeIndex([t]))
    assert np.isnan(float(result.at[t, "sector_rel_strength"]))
```

### Test Case 7 — NaN when sector history < _MIN_HIST

```python
def test_nan_when_sector_history_too_short():
    close = _make_close(300)
    sector = _make_sector(200)   # sector too short
    t = close.index[-1]
    result = SectorFeatures().compute(close, {"BANK": sector}, "BANK", pd.DatetimeIndex([t]))
    assert np.isnan(float(result.at[t, "sector_rel_strength"]))
```

### Test Case 8 — no look-ahead: mutating skip region (t-20..t) leaves signal unchanged

```python
def test_no_lookahead_skip_region():
    close = _make_close(300)
    sector = _make_sector(300)
    t = close.index[270]
    ref = SectorFeatures().compute(close, {"BANK": sector}, "BANK", pd.DatetimeIndex([t]))

    t_pos = close.index.get_loc(t)
    close_mutated = close.copy()
    close_mutated.iloc[t_pos - 20 : t_pos + 1] = 999.0   # mutate skip region

    result = SectorFeatures().compute(close_mutated, {"BANK": sector}, "BANK",
                                      pd.DatetimeIndex([t]))
    assert abs(float(ref.at[t, "sector_rel_strength"]) -
               float(result.at[t, "sector_rel_strength"])) < 1e-5
```

### Test Case 9 — matches manual calculation

```python
def test_matches_manual_calculation():
    close = _make_close()
    sector = _make_sector()
    t = close.index[-1]
    sym_mom = float(np.log(close.iloc[-22] / close.iloc[-253]))
    sec_mom = float(np.log(sector.iloc[-22] / sector.iloc[-253]))
    expected = sym_mom - sec_mom
    result = SectorFeatures().compute(close, {"BANK": sector}, "BANK", pd.DatetimeIndex([t]))
    assert abs(float(result.at[t, "sector_rel_strength"]) - expected) < 1e-4
```

### Test Case 10 — multiple rebalance dates produce correct NaN pattern

With `_MIN_HIST = 253`, `hist` at `close.index[k]` contains `k+1` prices. The signal is NaN
when `k+1 < 253`, i.e., `k < 252`. So `close.index[251]` → NaN, `close.index[252]` → finite.

```python
def test_multiple_dates_nan_pattern():
    close = _make_close(300)
    sector = _make_sector(300)
    dates = pd.DatetimeIndex([close.index[251], close.index[252], close.index[-1]])
    result = SectorFeatures().compute(close, {"BANK": sector}, "BANK", dates)
    # index[251]: 252 prices available — below _MIN_HIST=253 → NaN
    assert np.isnan(float(result.at[close.index[251], "sector_rel_strength"]))
    # index[252]: exactly 253 prices available — meets _MIN_HIST → finite
    assert not np.isnan(float(result.at[close.index[252], "sector_rel_strength"]))
    # index[-1]: 300 prices available → finite
    assert not np.isnan(float(result.at[close.index[-1], "sector_rel_strength"]))
```

### Test Case 11 — TypeError on non-DatetimeIndex symbol_close

```python
def test_raises_on_non_datetime_close():
    close_bad = pd.Series([100.0] * 300, index=range(300), name="SYM")
    sector = _make_sector()
    with pytest.raises(TypeError):
        SectorFeatures().compute(close_bad, {"BANK": sector}, "BANK",
                                 pd.DatetimeIndex([_make_close().index[-1]]))
```

### Test Case 12 — TypeError on non-DatetimeIndex sector Series

```python
def test_raises_on_non_datetime_sector():
    close = _make_close()
    sector_bad = pd.Series([1000.0] * 300, index=range(300), name="BANK_IDX")
    with pytest.raises(TypeError):
        SectorFeatures().compute(close, {"BANK": sector_bad}, "BANK",
                                 pd.DatetimeIndex([close.index[-1]]))
```

### Test Case 13 — ValueError on duplicate symbol_close timestamps

```python
def test_raises_on_duplicate_close():
    close = _make_close()
    sector = _make_sector()
    with pytest.raises(ValueError):
        SectorFeatures().compute(pd.concat([close, close.iloc[:1]]),
                                 {"BANK": sector}, "BANK",
                                 pd.DatetimeIndex([close.index[-1]]))
```

### Test Case 14 — non-trading rebalance date uses last available close

Use a date guaranteed to be after the last trading day in the series (no ambiguity about
whether +1 day is still a business day). The hist at this future date equals the hist at
`close.index[-1]`, so the result must be identical.

```python
def test_non_trading_rebalance_date():
    close = _make_close()
    sector = _make_sector()
    last_trading = close.index[-1]
    # A date 30 days after the last trading day — definitely not in the series.
    future_date = last_trading + pd.Timedelta(days=30)
    ref = SectorFeatures().compute(close, {"BANK": sector}, "BANK",
                                   pd.DatetimeIndex([last_trading]))
    result = SectorFeatures().compute(close, {"BANK": sector}, "BANK",
                                      pd.DatetimeIndex([future_date]))
    assert abs(float(ref.at[last_trading, "sector_rel_strength"]) -
               float(result.at[future_date, "sector_rel_strength"])) < 1e-5
```

---

## File Changes

| File | Action | Notes |
| --- | --- | --- |
| `src/csm/features/sector.py` | Rewrite | Per-symbol API, float32 output |
| `tests/unit/features/test_sector.py` | Create | 14 test cases |
| `docs/plans/phase2_signal_research/PLAN.md` | Update | Mark Phase 2.3 checklist complete |
| `docs/plans/phase2_signal_research/phase2.3_sector_features.md` | Create | This file |

`pipeline.py` is **not** changed in this phase. Integration of sector features into the pipeline
requires a sector_closes dict built from universe-filtered stock closes — that construction
belongs in Phase 2.4 alongside the rest of the pipeline assembly.

---

## Success Criteria

- [x] `uv run pytest tests/unit/features/test_sector.py -v` exits 0
- [x] `uv run pytest tests/unit/features/ -v` exits 0 (no regressions)
- [x] `uv run mypy src/csm/features/sector.py` exits 0
- [x] `uv run ruff check src/csm/features/sector.py` exits 0
- [x] All 14 test cases implemented and passing
- [x] No test uses the old wide-matrix API
- [x] `sector_rel_strength == 0` when symbol equals sector index

---

## Completion Notes

All deliverables completed on 2026-04-25.

- Old wide-matrix API (`relative_strength(prices, sector_map)`) fully replaced with
  `compute(symbol_close, sector_closes, symbol_sector, rebalance_dates)`
- `_MIN_HIST = 253` chosen: 253 prices give valid iloc[-22] (t-21) and iloc[-253] (t-252),
  the two boundary prices for mom_12_1 — consistent with Phase 2.1 offsets (start_td=252)
- Private helper `_mom_12_1(hist)` shared by both symbol and sector computation, returning
  NaN if any boundary price is non-positive or NaN
- `rebalance_dates` validated as DatetimeIndex (added after plan review)
- Test Cases 3 and 4 use deterministic drift-only price series (no random noise) to guarantee
  sign of relative strength — multiplying a price series by a constant leaves log returns
  unchanged, so distinct drift rates are required
- Test Case 10 uses `close.index[251]` (252 prices → NaN) and `close.index[252]` (253 prices
  → finite) to verify the boundary condition precisely
- Test Case 14 uses a +30-day future date to guarantee a non-trading date without relying on
  assumptions about weekday alignment
- `pipeline.py` integration deferred to Phase 2.4; the new API is pipeline-ready

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Sonnet 4.6)
**Status:** Complete
**Completed:** 2026-04-25
