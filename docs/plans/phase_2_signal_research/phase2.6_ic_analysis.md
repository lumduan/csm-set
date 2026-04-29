# Phase 2.6 - IC Analysis

**Feature:** Information Coefficient analysis — Pearson IC, Spearman rank IC, ICIR, decay curves, and summary table per signal
**Branch:** `feature/phase-2-signal-research`
**Created:** 2026-04-27
**Status:** Complete — 2026-04-27
**Depends On:** Phase 2.4 (FeaturePipeline — panel DataFrame with MultiIndex (date, symbol) + forward return columns), Phase 2.5 (CrossSectionalRanker — rank/quintile columns)

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

Phase 2.6 replaces the provisional `ICAnalyzer` (which accepted wide DataFrames with date rows and symbol columns) with the specification-compliant implementation from `PLAN.md`. The new API operates on the panel DataFrame produced by `FeaturePipeline` and ranked by `CrossSectionalRanker`, indexed by `(date, symbol)` MultiIndex.

Five public methods are provided:

- `compute_ic(panel_df, signal_col, forward_ret_col)` — Pearson IC time series per rebalance date
- `compute_rank_ic(panel_df, signal_col, forward_ret_col)` — Spearman rank IC time series
- `compute_icir(ic_series)` — ICIR scalar from an IC time series
- `compute_decay_curve(panel_df, signal_col, horizons)` — mean IC by forward horizon
- `summary_table(panel_df, signal_cols, horizon=1)` — aggregated stats table for multiple signals

An `ICResult` dataclass is also exported as a structured container for use in the Phase 2.7 notebook.

This interface is consumed by Phase 2.7 `02_signal_research.ipynb` for IC time series plots, ICIR ranking, decay curve visualisation, and the Phase 3 composite signal gate (ICIR > 0.3).

### Parent Plan Reference

- `docs/plans/phase2_signal_research/PLAN.md`

### Key Deliverables

1. `src/csm/research/ic_analysis.py` — `ICAnalyzer` and `ICResult` rewritten to match PLAN spec
2. `tests/unit/research/test_ic_analysis.py` — full test suite (≥ 10 tests)

---

## AI Prompt

The following prompt was used to generate this phase:

```text
🎯 Objective
Implement Phase 2.6 - IC Analysis for the signal research project by:
- Carefully planning the implementation based on project documentation and standards
- Creating a detailed plan markdown file before coding
- Implementing the phase after the plan is complete
- Updating project documentation with progress and completion notes
- Committing all changes when the job is finished

📋 Context
- The project is located at /Users/sarat/Code/csm-set
- The current focus is Phase 2.6 - IC Analysis, as described in docs/plans/phase2_signal_research/PLAN.md
- The last completed phase is Phase 2.5 - Ranking (see docs/plans/phase2_signal_research/phase2.5_ranking.md)
- All planning and documentation must follow the format in docs/plans/examples/phase1-sample.md
- The project enforces strict architectural, documentation, and workflow standards, including type safety,
  async-first patterns, Pydantic validation (with documented exceptions), comprehensive error handling,
  and rigorous testing

🔧 Requirements
- Read and understand docs/plans/phase2_signal_research/PLAN.md, focusing on Phase 2.6 - IC Analysis
- Review docs/plans/phase2_signal_research/phase2.5_ranking.md for context on the last completed phase
- Before coding, create a detailed plan for Phase 2.6 as a markdown file at
  docs/plans/phase2_signal_research/phase2.6_ic_analysis.md, following the format in
  docs/plans/examples/phase1-sample.md. The plan must include the prompt used for this task
- Only begin implementation after the plan is complete and documented
- Upon completion, update docs/plans/phase2_signal_research/PLAN.md and
  docs/plans/phase2_signal_research/phase2.6_ic_analysis.md with progress notes, completion dates,
  and any issues encountered
- Ensure all code and documentation changes follow the project's core architectural principles,
  documentation standards, and workflow requirements
- Commit all changes when the job is finished

📁 Code Context
- docs/plans/phase2_signal_research/PLAN.md (project phase plan, focus on Phase 2.6 - IC Analysis)
- docs/plans/phase2_signal_research/phase2.5_ranking.md (last completed phase)
- docs/plans/examples/phase1-sample.md (plan and documentation format reference)
- All relevant architectural and documentation standards as described in the project

✅ Expected Output
- A detailed plan for Phase 2.6 - IC Analysis as docs/plans/phase2_signal_research/phase2.6_ic_analysis.md,
  including the prompt used for this task and following the required format
- Implementation of Phase 2.6 - IC Analysis according to the plan and project standards
- Updated docs/plans/phase2_signal_research/PLAN.md and
  docs/plans/phase2_signal_research/phase2.6_ic_analysis.md with progress notes, completion dates,
  and any issues encountered
- All changes committed to the repository upon completion
```

---

## Scope

### In Scope

| Component | Description | Status |
| --- | --- | --- |
| `ICAnalyzer.compute_ic()` | Pearson IC per rebalance date; NaN when < 10 symbols | Complete |
| `ICAnalyzer.compute_rank_ic()` | Spearman rank IC per rebalance date; NaN when < 10 symbols | Complete |
| `ICAnalyzer.compute_icir()` | ICIR = mean/std; NaN when < 12 non-NaN IC observations | Complete |
| `ICAnalyzer.compute_decay_curve()` | Mean Pearson IC by forward horizon using `fwd_ret_{h}m` columns | Complete |
| `ICAnalyzer.summary_table()` | Table: signal → Mean_IC, Std_IC, ICIR, t_stat, pct_positive | Complete |
| `ICResult` dataclass | Structured container for a single signal's IC analysis outputs | Complete |
| MultiIndex validation | `_validate_panel()` shared with ranking.py pattern | Complete |
| Input validation | TypeError/ValueError at every public method boundary | Complete |
| Unit tests | ≥ 10 tests covering all PLAN-required and edge cases | Complete |

### Out of Scope

- Quintile return spread analysis (Phase 2.7 notebook responsibility)
- Composite signal design and weighting (Phase 2.7)
- Persistence of IC results to `results/signals/` (Phase 2.7 notebook responsibility)
- Integration tests requiring real parquet data

### Existing API — Breaking Change

The previous `ICAnalyzer.compute_ic(signals, forward_returns)` accepted wide DataFrames (date rows × symbol columns). This is replaced by `compute_ic(panel_df, signal_col, forward_ret_col)` per `PLAN.md`. The single existing test is replaced. The old `icir()` and `decay_curve()` methods are replaced by `compute_icir()` and `compute_decay_curve()` respectively.

---

## Design Decisions

### 1. Raw pandas types: same architectural exception as Phases 2.1–2.5

`ICAnalyzer` receives and returns `pd.DataFrame`/`pd.Series` without Pydantic wrappers, consistent with the Phase 2 research layer exception (see `phase2.4_feature_pipeline.md`, Design Decision 1). Manual input guards (`TypeError`, `ValueError`) are added at every method boundary.

### 2. Minimum cross-section size of 10 produces NaN

When a rebalance date has fewer than 10 symbols with both signal and forward return non-NaN, the IC for that date is recorded as NaN. This threshold prevents spurious correlations from very small cross-sections from inflating the IC time series or the ICIR.

### 3. ICIR requires a minimum of 12 non-NaN IC periods

Fewer than 12 periods yields an unreliable estimate of mean and standard deviation of IC. `compute_icir()` returns `float('nan')` in this case rather than a misleading scalar, consistent with the PLAN.md specification. When `std(IC, ddof=1) == 0`, `NaN` is returned to avoid division by zero.

### 4. `ddof=1` (sample std) throughout

`std(ddof=1)` is the unbiased estimator and is the pandas default. This is used in both `compute_icir()` and `summary_table()`. The older `icir()` method used `ddof=0`; this is corrected.

### 5. Decay curve maps horizon integers to `fwd_ret_{h}m` column names

`compute_decay_curve()` accepts a list of integer horizons and looks up the corresponding `fwd_ret_{h}m` column in the panel. The known mappings `{1, 2, 3, 6, 12}` are pre-defined. Horizons without a matching column receive NaN in the output Series. This makes the decay curve callable with any subset of horizons available in the panel.

### 6. `t_stat = ICIR × sqrt(T)` in `summary_table`

Following the standard result for testing mean IC against zero, where `T` is the number of non-NaN IC observations in the time series. This is consistent with Grinold & Kahn (1999). `t_stat` is NaN when ICIR is NaN (i.e., fewer than 12 periods).

### 7. `_validate_panel()` mirrors `ranking.py`

The same three-step validation (type check → MultiIndex check → level name check) is reproduced in `ic_analysis.py` without importing from `ranking.py`, keeping the two modules independent. Both raise `TypeError` for non-DataFrames and `ValueError` for bad MultiIndex structure.

### 8. `ICResult` dataclass as a structured output container

`ICResult` captures the full output of IC analysis for one signal and one horizon, as specified in `PLAN.md`. It is exported for use in the Phase 2.7 notebook as a convenience container, but no method in `ICAnalyzer` returns it directly — the notebook constructs it from the individual method outputs.

---

## Function Signatures

```python
from __future__ import annotations

import math
import logging
from dataclasses import dataclass

import pandas as pd

_MIN_CROSS_SECTION: int = 10
_MIN_IC_PERIODS: int = 12
_HORIZON_TO_COL: dict[int, str] = {
    1: "fwd_ret_1m",
    2: "fwd_ret_2m",
    3: "fwd_ret_3m",
    6: "fwd_ret_6m",
    12: "fwd_ret_12m",
}


@dataclass
class ICResult:
    signal_name: str
    ic_series: pd.Series        # index = rebalance_dates, values = Pearson IC
    rank_ic_series: pd.Series   # Spearman IC
    icir: float
    rank_icir: float
    mean_ic: float
    std_ic: float
    t_stat: float
    pct_positive: float         # fraction of months with IC > 0
    decay_curve: pd.Series      # index = horizons [1,2,3,6,12], values = mean IC


class ICAnalyzer:
    """Compute IC, ICIR, and decay diagnostics for panel-based signals."""

    def compute_ic(
        self,
        panel_df: pd.DataFrame,
        signal_col: str,
        forward_ret_col: str,
    ) -> pd.Series:
        """Pearson IC per rebalance date.

        For each date, correlates `signal_col` with `forward_ret_col` across
        the available symbol cross-section (NaN rows dropped pairwise).
        Returns NaN for dates with fewer than _MIN_CROSS_SECTION valid pairs.

        Args:
            panel_df: MultiIndex (date, symbol) panel from FeaturePipeline.
            signal_col: Name of the signal feature column to evaluate.
            forward_ret_col: Name of the forward return column (e.g. 'fwd_ret_1m').

        Returns:
            pd.Series indexed by rebalance date with Pearson IC values.
            Name = 'ic'.

        Raises:
            TypeError: If panel_df is not a pd.DataFrame.
            ValueError: If panel_df.index is not a MultiIndex with names
                        ["date", "symbol"], or if signal_col / forward_ret_col
                        are not columns in panel_df.
        """

    def compute_rank_ic(
        self,
        panel_df: pd.DataFrame,
        signal_col: str,
        forward_ret_col: str,
    ) -> pd.Series:
        """Spearman rank IC per rebalance date.

        Identical contract to compute_ic() except correlation uses Spearman
        method (ranks both signal and return before correlating).

        Returns:
            pd.Series indexed by rebalance date.
            Name = 'rank_ic'.
        """

    def compute_icir(self, ic_series: pd.Series) -> float:
        """Information Coefficient Information Ratio.

        ICIR = mean(IC) / std(IC, ddof=1) over non-NaN observations.
        Returns float('nan') when fewer than _MIN_IC_PERIODS non-NaN
        observations are present, or when std == 0.

        Raises:
            TypeError: If ic_series is not a pd.Series.
        """

    def compute_decay_curve(
        self,
        panel_df: pd.DataFrame,
        signal_col: str,
        horizons: list[int],
    ) -> pd.Series:
        """Mean Pearson IC by forward horizon.

        For each horizon h in horizons, looks up 'fwd_ret_{h}m' in panel_df
        and computes mean(IC time series). Horizons without a matching column
        receive NaN.

        Returns:
            pd.Series indexed by horizon integers with mean IC values.
            Name = 'mean_ic'.
        """

    def summary_table(
        self,
        panel_df: pd.DataFrame,
        signal_cols: list[str],
        horizon: int = 1,
    ) -> pd.DataFrame:
        """Aggregated IC statistics table for multiple signals.

        Returns:
            pd.DataFrame indexed by signal name with columns:
              Mean_IC, Std_IC, ICIR, t_stat, pct_positive

        Raises:
            ValueError: If the forward return column for the given horizon
                        is not present in panel_df.
        """
```

---

## Implementation Steps

### Step 1 — `_validate_panel()` helper

Mirror the same pattern from `ranking.py`:

```python
def _validate_panel(panel_df: object) -> pd.DataFrame:
    if not isinstance(panel_df, pd.DataFrame):
        raise TypeError(f"panel_df must be a pd.DataFrame, got {type(panel_df).__name__}")
    df: pd.DataFrame = panel_df
    if not isinstance(df.index, pd.MultiIndex):
        raise ValueError(
            f"panel_df.index must be a pd.MultiIndex; got {type(df.index).__name__}"
        )
    if list(df.index.names) != ["date", "symbol"]:
        raise ValueError(
            f"panel_df.index.names must be ['date', 'symbol']; got {list(df.index.names)}"
        )
    return df
```

### Step 2 — `compute_ic()` core loop

```python
def compute_ic(self, panel_df, signal_col, forward_ret_col) -> pd.Series:
    df = _validate_panel(panel_df)
    # validate column existence
    for col in (signal_col, forward_ret_col):
        if col not in df.columns:
            raise ValueError(f"{col!r} not found in panel_df columns")

    dates = df.index.get_level_values("date").unique()
    ic_vals: dict[pd.Timestamp, float] = {}
    for date in dates:
        cross = df.xs(date, level="date")[[signal_col, forward_ret_col]].dropna()
        if len(cross) < _MIN_CROSS_SECTION:
            ic_vals[date] = float("nan")
        else:
            ic_vals[date] = float(cross[signal_col].corr(cross[forward_ret_col], method="pearson"))
    return pd.Series(ic_vals, name="ic")
```

### Step 3 — `compute_rank_ic()` — identical loop, `method="spearman"`

```python
def compute_rank_ic(self, panel_df, signal_col, forward_ret_col) -> pd.Series:
    # identical structure to compute_ic, method="spearman", name="rank_ic"
```

### Step 4 — `compute_icir()` with minimum period guard

```python
def compute_icir(self, ic_series: pd.Series) -> float:
    if not isinstance(ic_series, pd.Series):
        raise TypeError(...)
    valid = ic_series.dropna()
    if len(valid) < _MIN_IC_PERIODS:
        return float("nan")
    std = float(valid.std(ddof=1))
    if std == 0.0:
        return float("nan")
    return float(valid.mean() / std)
```

### Step 5 — `compute_decay_curve()` via horizon column lookup

```python
def compute_decay_curve(self, panel_df, signal_col, horizons) -> pd.Series:
    df = _validate_panel(panel_df)
    if signal_col not in df.columns:
        raise ValueError(...)
    mean_ic: dict[int, float] = {}
    for h in horizons:
        col = _HORIZON_TO_COL.get(h, f"fwd_ret_{h}m")
        if col not in df.columns:
            mean_ic[h] = float("nan")
            continue
        ic_s = self.compute_ic(df, signal_col, col)
        mean_ic[h] = float(ic_s.mean()) if not ic_s.isna().all() else float("nan")
    return pd.Series(mean_ic, name="mean_ic")
```

### Step 6 — `summary_table()` aggregation

```python
def summary_table(self, panel_df, signal_cols, horizon=1) -> pd.DataFrame:
    df = _validate_panel(panel_df)
    fwd_col = _HORIZON_TO_COL.get(horizon, f"fwd_ret_{horizon}m")
    if fwd_col not in df.columns:
        raise ValueError(...)
    rows = []
    for col in signal_cols:
        if col not in df.columns:
            raise ValueError(...)
        ic_s = self.compute_ic(df, col, fwd_col)
        valid = ic_s.dropna()
        mean_ic = float(valid.mean()) if len(valid) > 0 else float("nan")
        std_ic = float(valid.std(ddof=1)) if len(valid) > 1 else float("nan")
        icir = self.compute_icir(ic_s)
        t_stat = icir * math.sqrt(len(valid)) if not math.isnan(icir) else float("nan")
        pct_pos = float((valid > 0).mean()) if len(valid) > 0 else float("nan")
        rows.append({"signal": col, "Mean_IC": mean_ic, "Std_IC": std_ic,
                     "ICIR": icir, "t_stat": t_stat, "pct_positive": pct_pos})
    return pd.DataFrame(rows).set_index("signal")
```

### Step 7 — `__all__` export

```python
__all__: list[str] = ["ICAnalyzer", "ICResult"]
```

Update `src/csm/research/__init__.py` to export `ICResult`.

---

## Test Plan

All tests use in-memory `pd.DataFrame` fixtures. No disk I/O.

### Fixtures

```python
_TZ = "Asia/Bangkok"
_N_DATES = 12
_N_SYMBOLS = 15

@pytest.fixture
def panel_df() -> pd.DataFrame:
    """12 dates × 15 symbols. signal = fwd_ret_1m + small noise (high IC expected)."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2023-01-31", periods=_N_DATES, freq="ME", tz=_TZ)
    symbols = [f"SET:S{i:02d}" for i in range(_N_SYMBOLS)]
    idx = pd.MultiIndex.from_product([dates, symbols], names=["date", "symbol"])
    signal = rng.standard_normal(len(idx)).astype("float32")
    fwd_ret = (signal + rng.standard_normal(len(idx)) * 0.1).astype("float32")
    return pd.DataFrame({"mom_12_1": signal, "fwd_ret_1m": fwd_ret}, index=idx)
```

### Test Case 1 — IC on perfect synthetic signal (known correlation = 1.0)

Build a panel where `signal == fwd_ret_1m` exactly for every date. `compute_ic` should
return 1.0 for all dates.

### Test Case 2 — IC values in [-1, 1] range

On the noisy panel fixture, verify all non-NaN IC values are in `[-1, 1]`.

### Test Case 3 — NaN when fewer than 10 symbols on a date

Build a panel where one date has only 5 symbols with non-NaN values.
`compute_ic` should return NaN for that date only; other dates unaffected.

### Test Case 4 — Rank IC uses Spearman (different from Pearson on non-linear data)

Build a panel where signal is the sign of forward_return (i.e., `+1/-1`).
Pearson IC will be lower than Spearman IC because Spearman captures the monotone
relationship. Assert `compute_rank_ic > compute_ic` for at least one date.

### Test Case 5 — ICIR matches manual mean/std calculation

Create a known IC Series (12 values), compute manually, compare with `compute_icir`.

```python
ic = pd.Series([0.05, 0.10, -0.02, 0.08, 0.12, 0.03,
                0.07, 0.09, -0.01, 0.06, 0.11, 0.04])
expected = ic.mean() / ic.std(ddof=1)
assert abs(analyzer.compute_icir(ic) - expected) < 1e-10
```

### Test Case 6 — `compute_icir` returns NaN when fewer than 12 periods

```python
short_ic = pd.Series([0.05, 0.10, 0.08])  # only 3 periods
assert math.isnan(analyzer.compute_icir(short_ic))
```

### Test Case 7 — Decay curve returns correct horizon index

Build a panel with `fwd_ret_1m`, `fwd_ret_3m`, `fwd_ret_6m` columns.
`compute_decay_curve(panel, signal, [1, 3, 6])` returns a Series with index `[1, 3, 6]`.
`compute_decay_curve(panel, signal, [1, 2])` returns NaN for horizon 2 (column absent).

### Test Case 8 — Decay curve values are mean IC (not IC of single date)

For a 12-date panel, the decay curve value at horizon 1 should equal
`compute_ic(panel, signal, 'fwd_ret_1m').mean()`.

### Test Case 9 — `summary_table` columns and shape

```python
table = analyzer.summary_table(panel_df, ["mom_12_1"])
assert list(table.columns) == ["Mean_IC", "Std_IC", "ICIR", "t_stat", "pct_positive"]
assert table.index.tolist() == ["mom_12_1"]
```

### Test Case 10 — `summary_table` t_stat = ICIR * sqrt(T)

Manually verify `t_stat == ICIR * sqrt(T)` for a controlled IC series.

### Test Case 11 — Input validation: TypeError on non-DataFrame

```python
with pytest.raises(TypeError, match="pd.DataFrame"):
    analyzer.compute_ic("not_a_df", "signal", "fwd_ret_1m")
```

### Test Case 12 — Input validation: ValueError on flat index

Build a DataFrame with a flat RangeIndex. Verify `ValueError` is raised.

### Test Case 13 — Input validation: ValueError on missing column

```python
with pytest.raises(ValueError, match="not found in panel_df"):
    analyzer.compute_ic(panel_df, "nonexistent_signal", "fwd_ret_1m")
```

---

## File Changes

| File | Action | Notes |
| --- | --- | --- |
| `src/csm/research/ic_analysis.py` | Rewrite | New panel-based API: `compute_ic`, `compute_rank_ic`, `compute_icir`, `compute_decay_curve`, `summary_table`, `ICResult` |
| `src/csm/research/__init__.py` | Modify | Add `ICResult` to exports |
| `tests/unit/research/test_ic_analysis.py` | Rewrite | ≥ 10 tests covering all PLAN-required and edge cases |
| `docs/plans/phase2_signal_research/PLAN.md` | Modify | Mark Phase 2.6 checklist complete |
| `docs/plans/phase2_signal_research/phase2.6_ic_analysis.md` | Create | This file |

---

## Success Criteria

- [x] `uv run pytest tests/unit/research/test_ic_analysis.py -v` exits 0
- [x] `uv run pytest tests/unit/research/ -v` exits 0 (no regressions)
- [x] `uv run mypy src/csm/research/ic_analysis.py` exits 0
- [x] `uv run ruff check src/csm/research/ic_analysis.py` exits 0
- [x] IC on perfect signal returns 1.0 for all dates
- [x] IC values in `[-1, 1]`
- [x] IC is NaN when fewer than 10 symbols on a date
- [x] ICIR matches manual mean/std formula
- [x] ICIR returns NaN when fewer than 12 periods
- [x] Decay curve indexed by horizons; NaN for missing columns
- [x] `summary_table` columns: Mean_IC, Std_IC, ICIR, t_stat, pct_positive
- [x] `t_stat = ICIR * sqrt(T)` verified
- [x] Input validation: TypeError for non-DataFrame, ValueError for flat index and missing columns

---

## Completion Notes

All deliverables completed on 2026-04-27.

- Rewrote `ICAnalyzer` to match PLAN.md spec: panel-based API operating on MultiIndex `(date, symbol)` DataFrames.
- Added `_validate_panel()` helper mirroring `ranking.py` pattern (Design Decision 7).
- Used `ddof=1` sample std for ICIR, correcting the old `ddof=0` (Design Decision 4).
- `compute_icir()` returns NaN for < 12 periods and for zero std (Design Decision 3).
- `compute_decay_curve()` maps horizon integers to `fwd_ret_{h}m` columns (Design Decision 5).
- `t_stat = ICIR * sqrt(T)` in `summary_table` (Design Decision 6).
- Added `ICResult` dataclass as structured container for Phase 2.7 notebook (Design Decision 8).
- 13 unit tests written; all 5 PLAN-required cases covered plus 8 edge-case tests.
- No regressions in Phases 2.1–2.5 test suites.

### Issues Encountered

1. **Old `ICAnalyzer` used wide DataFrames** — The previous implementation accepted `signals: pd.DataFrame` (date rows × symbol columns) rather than a panel. This API is incompatible with the PLAN.md spec and has been replaced entirely. The single existing test was also replaced.
2. **`ddof=0` vs `ddof=1` for ICIR** — The old `icir()` used `ddof=0`. Changed to `ddof=1` (sample std, pandas default) for statistical correctness.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Sonnet 4.6)
**Status:** Complete
**Completed:** 2026-04-27
