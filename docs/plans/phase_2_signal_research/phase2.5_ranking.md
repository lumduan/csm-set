# Phase 2.5 - Ranking

**Feature:** Cross-sectional percentile ranking and quintile labelling per rebalance date
**Branch:** `feature/phase-2-signal-research`
**Created:** 2026-04-26
**Status:** Complete — 2026-04-26
**Depends On:** Phase 2.4 (FeaturePipeline — panel DataFrame with MultiIndex (date, symbol))

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

Phase 2.5 replaces the provisional `CrossSectionalRanker` (which computed a composite z-score
internally and accepted a `date` argument) with the specification-compliant implementation from
`PLAN.md`. The new API ranks symbols within each date group for any named signal column, producing:

- `{signal_col}_rank` — percentile rank in `(0, 1]`, using `rank(method='average', pct=True)`
- `{signal_col}_quintile` — integer quintile label 1–5 per date

Two public methods are provided:

- `rank(panel_df, signal_col)` — rank a single named column and append the two new columns
- `rank_all(panel_df)` — apply `rank()` to every numeric, non-forward-return feature column

This interface is consumed by Phase 2.6 `ICAnalyzer` (rank columns for Spearman IC) and
Phase 2.7 `02_signal_research.ipynb` (quintile labels for Q5-Q1 spread analysis).

### Parent Plan Reference

- `docs/plans/phase2_signal_research/PLAN.md`

### Key Deliverables

1. `src/csm/research/ranking.py` — `CrossSectionalRanker` rewritten to match PLAN spec
2. `tests/unit/research/test_ranking.py` — full test suite (9 tests)

---

## AI Prompt

The following prompt was used to generate this phase:

```text
🎯 Objective
Develop a comprehensive plan and implementation for Phase 2.5 - Ranking in the signal research
project, following the established documentation, architectural, and workflow standards. The
process must include planning, documentation, implementation, and progress tracking as specified.

📋 Context
- The project is located at /Users/sarat/Code/csm-set.
- The current focus is Phase 2.5 - Ranking, as described in
  docs/plans/phase2_signal_research/PLAN.md.
- The previous completed phase is Phase 2.4 - Feature Pipeline (see
  docs/plans/phase2_signal_research/phase2.4_feature_pipeline.md).
- All planning and documentation must follow the format in docs/plans/examples/phase1-sample.md.
- The project enforces strict architectural, documentation, and workflow standards, including
  type safety, async-first patterns, Pydantic validation (with documented exceptions),
  comprehensive error handling, and rigorous testing.

🔧 Requirements
- Carefully read and understand docs/plans/phase2_signal_research/PLAN.md, focusing on
  Phase 2.5 - Ranking.
- Review docs/plans/phase2_signal_research/phase2.4_feature_pipeline.md for context on the
  last completed phase.
- Before coding, create a detailed plan for Phase 2.5 as a markdown file at
  docs/plans/phase2_signal_research/phase2.5_ranking.md, following the format in
  docs/plans/examples/phase1-sample.md. The plan must include the prompt used for this task.
- Only begin implementation after the plan is complete and documented.
- Upon completion, update docs/plans/phase2_signal_research/PLAN.md and
  docs/plans/phase2_signal_research/phase2.5_ranking.md with progress notes, completion dates,
  and any issues encountered.
- Ensure all code and documentation changes follow the project's core architectural principles,
  documentation standards, and workflow requirements.
- Commit all changes when the job is finished.

📁 Code Context
- docs/plans/phase2_signal_research/PLAN.md (project phase plan, focus on Phase 2.5 - Ranking)
- docs/plans/phase2_signal_research/phase2.4_feature_pipeline.md (last completed phase)
- docs/plans/examples/phase1-sample.md (plan and documentation format reference)
- All relevant architectural and documentation standards as described in the project

✅ Expected Output
- A detailed plan for Phase 2.5 - Ranking as docs/plans/phase2_signal_research/phase2.5_ranking.md,
  including the prompt used for this task and following the required format.
- Implementation of Phase 2.5 - Ranking according to the plan and project standards.
- Updated docs/plans/phase2_signal_research/PLAN.md and
  docs/plans/phase2_signal_research/phase2.5_ranking.md with progress notes, completion dates,
  and any issues encountered.
- All changes committed to the repository upon completion.
```

---

## Scope

### In Scope

| Component | Description | Status |
| --- | --- | --- |
| `CrossSectionalRanker.rank()` | Rank one named signal column per date; append `{col}_rank` and `{col}_quintile` | Complete |
| `CrossSectionalRanker.rank_all()` | Apply `rank()` to every numeric, non-fwd-ret feature column | Complete |
| MultiIndex validation | Validate panel has a `MultiIndex` with levels `["date", "symbol"]` | Complete |
| Tie handling | `rank(method='average')` — verified by a tie-case unit test | Complete |
| Quintile fallback | Graceful degradation for small / tied cross-sections (< 5 unique bins) | Complete |
| NaN handling | Symbols with NaN in signal excluded; receive NaN in rank/quintile columns | Complete |
| Unit tests | 9 tests covering all PLAN-required and edge cases | Complete |

### Out of Scope

- Composite score construction (done in notebook Phase 2.7)
- ICAnalyzer (Phase 2.6)
- Persistence of ranked panels to parquet (pipeline / notebook responsibility)
- Integration tests requiring real parquet data

### Existing API — Breaking Change

The previous `CrossSectionalRanker.rank(feature_matrix, date)` is replaced by
`rank(panel_df, signal_col)` per `PLAN.md`. The single existing test is updated.

---

## Design Decisions

### 1. Raw pandas types: same architectural exception as Phases 2.1–2.4

`CrossSectionalRanker` receives and returns `pd.DataFrame` without Pydantic wrappers, consistent
with the Phase 2 research layer exception (see `phase2.4_feature_pipeline.md`, Design Decision 1).
Manual input guards (`TypeError`, `ValueError`) are added at every method boundary.

### 2. `rank(method='average', pct=True)` for Spearman-IC consistency

`method='average'` assigns tied values the mean of their would-be ranks, matching how
`scipy.stats.spearmanr` resolves ties. Using `method='first'` would break equivalence when
ties are present in the cross-section.

The resulting percentile rank range is `(0, 1]`: the minimum possible value approaches but
never equals 0 because `rank(pct=True)` computes `rank / N`.

### 3. Quintile assignment with `pd.qcut` and a tied-bin fallback

When a date's cross-section has very few symbols or many ties, `pd.qcut(ranks, q=5,
labels=[1,2,3,4,5], duplicates='drop')` may silently produce fewer than 5 bins, causing a
`ValueError` because the label list length no longer matches the bin count.

**Fallback strategy:** if `pd.qcut` with 5 bins raises `ValueError`, re-attempt with
`labels=False` (auto-increment integers) and then map the resulting bin indices to 1-based
quintile labels. If the fallback also fails (e.g., only 1 unique value), assign `NaN` for the
date's quintile column and log a warning. This keeps downstream code safe regardless of
cross-section size.

### 4. NaN symbols dropped silently before ranking

Symbols with NaN in the target signal column are excluded from `rank()` on that date.
Their `{col}_rank` and `{col}_quintile` entries in the output are NaN. This is consistent
with the FeaturePipeline behaviour (which drops NaN symbols during `build()`).

### 5. `rank_all()` ranks numeric columns only, skipping fwd-ret and already-ranked columns

`rank_all()` iterates `panel_df.select_dtypes(include='number').columns`. Forward return
columns (`fwd_ret_*`) and already-computed rank/quintile columns (`_rank`, `_quintile` suffixes)
are skipped. This prevents re-ranking of already-processed columns on repeated `rank_all()` calls.

### 6. MultiIndex validation at every method boundary

Both `rank()` and `rank_all()` call a shared `_validate_panel(panel_df)` helper that raises:
- `TypeError` if `panel_df` is not a `pd.DataFrame`
- `ValueError` if `panel_df.index` is not a `pd.MultiIndex`
- `ValueError` if the MultiIndex levels are not named `["date", "symbol"]`

Validating the index prevents unclear `KeyError` failures from `get_level_values("date")`.

### 7. Return type: copy semantics

Both methods return a new `pd.DataFrame` (copy of input plus new columns). The original
`panel_df` is never mutated.

---

## Function Signatures

```python
class CrossSectionalRanker:
    """Rank symbols cross-sectionally within each rebalance date."""

    def rank(
        self,
        panel_df: pd.DataFrame,
        signal_col: str,
    ) -> pd.DataFrame:
        """Compute cross-sectional percentile rank and quintile label for one signal.

        For each date in panel_df, ranks symbols by `signal_col` within that date's
        cross-section. Symbols with NaN in `signal_col` are excluded from ranking
        on that date and receive NaN in the output rank/quintile columns.

        Args:
            panel_df: MultiIndex (date, symbol) panel produced by FeaturePipeline.
                      Index must be a pd.MultiIndex with names ["date", "symbol"].
            signal_col: Name of the feature column to rank.

        Returns:
            Copy of panel_df with two additional columns:
              - `{signal_col}_rank`: float64, percentile rank in (0, 1].
                Ties resolved with method='average'.
              - `{signal_col}_quintile`: Int8 (nullable), quintile label 1–5.
                Computed via pd.qcut per date. NaN for excluded symbols and
                cross-sections where quintile bins cannot be formed.

        Raises:
            TypeError: If panel_df is not a pd.DataFrame.
            ValueError: If panel_df.index is not a MultiIndex with names
                        ["date", "symbol"], or if signal_col is not a column
                        in panel_df.
        """

    def rank_all(
        self,
        panel_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Apply rank() to every numeric feature column in panel_df.

        Skips forward-return columns (names starting with 'fwd_ret_') and columns
        that already end with '_rank' or '_quintile'. Ranks only numeric dtypes.

        Args:
            panel_df: MultiIndex (date, symbol) panel produced by FeaturePipeline.

        Returns:
            Copy of panel_df with rank and quintile columns for every qualifying
            feature column.

        Raises:
            TypeError: If panel_df is not a pd.DataFrame.
            ValueError: If panel_df.index is not a MultiIndex with names
                        ["date", "symbol"].
        """
```

---

## Implementation Steps

### Step 1 — `_validate_panel()` helper

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

### Step 2 — `_assign_quintiles()` helper with fallback

```python
def _assign_quintiles(ranks: pd.Series) -> pd.Series:
    """Assign quintile labels 1–5 to a percentile rank Series."""
    try:
        return pd.qcut(
            ranks, q=5, labels=[1, 2, 3, 4, 5], duplicates="drop"
        ).astype("Int8")
    except ValueError:
        pass
    try:
        bins = pd.qcut(ranks, q=5, labels=False, duplicates="drop")
        n_bins = int(bins.max()) + 1  # 0-based bin index
        label_map = {i: int(round(1 + i * 4 / max(n_bins - 1, 1))) for i in range(n_bins)}
        return bins.map(label_map).astype("Int8")
    except ValueError:
        logger.warning("Cannot assign quintiles for cross-section of size %d", len(ranks))
        return pd.Series(pd.NA, index=ranks.index, dtype="Int8")
```

### Step 3 — `rank()` core loop

```python
def rank(self, panel_df: pd.DataFrame, signal_col: str) -> pd.DataFrame:
    df = _validate_panel(panel_df)
    if signal_col not in df.columns:
        raise ValueError(f"signal_col {signal_col!r} not found in panel_df columns")

    result = df.copy()
    rank_col = f"{signal_col}_rank"
    quintile_col = f"{signal_col}_quintile"
    result[rank_col] = float("nan")
    result[quintile_col] = pd.array([pd.NA] * len(result), dtype="Int8")

    for date in result.index.get_level_values("date").unique():
        mask = result.index.get_level_values("date") == date
        values: pd.Series = result.loc[mask, signal_col]
        valid = values.dropna()
        if valid.empty:
            continue
        ranks = valid.rank(method="average", pct=True)
        result.loc[valid.index, rank_col] = ranks
        result.loc[valid.index, quintile_col] = _assign_quintiles(ranks)

    return result
```

### Step 4 — `rank_all()` delegation

```python
_SKIP_PREFIXES: tuple[str, ...] = ("fwd_ret_",)
_SKIP_SUFFIXES: tuple[str, ...] = ("_rank", "_quintile")

def rank_all(self, panel_df: pd.DataFrame) -> pd.DataFrame:
    df = _validate_panel(panel_df)
    result = df.copy()
    numeric_cols = df.select_dtypes(include="number").columns
    for col in numeric_cols:
        if any(col.startswith(p) for p in _SKIP_PREFIXES):
            continue
        if any(col.endswith(s) for s in _SKIP_SUFFIXES):
            continue
        result = self.rank(result, col)
    return result
```

### Step 5 — `__all__` export

Keep `__all__ = ["CrossSectionalRanker"]` unchanged.

---

## Test Plan

All tests use in-memory `pd.DataFrame` fixtures. No disk I/O.

### Fixture

```python
_TZ = "Asia/Bangkok"
_DATES = [pd.Timestamp("2024-01-31", tz=_TZ), pd.Timestamp("2024-02-29", tz=_TZ)]

@pytest.fixture
def panel_df() -> pd.DataFrame:
    """10 symbols × 2 dates, linearly spread mom_12_1 signal (SYM00=10 highest)."""
    symbols = [f"SYM{i:02d}" for i in range(10)]
    idx = pd.MultiIndex.from_product([_DATES, symbols], names=["date", "symbol"])
    signal = list(range(10, 0, -1)) * 2
    return pd.DataFrame({"mom_12_1": signal}, index=idx, dtype="float64")
```

### Test Case 1 — percentile ranks in (0, 1]

Verify `0 < rank <= 1` for all non-NaN entries.

### Test Case 2 — quintile counts balanced (~N/5)

For each date, each quintile label 1–5 should have exactly 2 symbols (10 symbols / 5 bins).

### Test Case 3 — highest signal → quintile 5, lowest → quintile 1

Verify ordering by checking `idxmax()` maps to quintile 5 and `idxmin()` to quintile 1.

### Test Case 4 — NaN symbol excluded; other dates unaffected

Set one symbol to NaN on one date. That symbol gets NaN rank/quintile on that date only.
Its rank on the other date is non-NaN and valid.

### Test Case 5 — `rank_all()` adds rank/quintile for all numeric features

A panel with two feature columns should produce four new columns: two `_rank` and two `_quintile`.

### Test Case 6 — `rank_all()` skips `fwd_ret_*` columns

A panel with `mom_12_1` and `fwd_ret_1m` should produce `mom_12_1_rank` but not `fwd_ret_1m_rank`.

### Test Case 7 — `ValueError` on missing signal_col

```python
with pytest.raises(ValueError, match="not found in panel_df columns"):
    CrossSectionalRanker().rank(panel_df, "nonexistent")
```

### Test Case 8 — tie handling: tied values share equal rank

Build a cross-section where multiple symbols have identical signal values. Verify the rank
column shows the same average rank for all tied symbols (e.g., three symbols tied for
positions 1–3 should each receive rank `2/N` not distinct ordinal ranks).

### Test Case 9 — small cross-section (< 5 symbols) does not raise

Build a panel with only 3 symbols. Calling `rank()` should not raise; quintile column
should be non-NaN for those 3 symbols (using the fallback path).

---

## File Changes

| File | Action | Notes |
| --- | --- | --- |
| `src/csm/research/ranking.py` | Rewrite | New `rank(panel_df, signal_col)` + `rank_all(panel_df)` API |
| `tests/unit/research/test_ranking.py` | Rewrite | 9 tests covering all PLAN-required and edge cases |
| `docs/plans/phase2_signal_research/PLAN.md` | Modify | Mark Phase 2.5 checklist complete |
| `docs/plans/phase2_signal_research/phase2.5_ranking.md` | Create | This file |

---

## Success Criteria

- [x] `uv run pytest tests/unit/research/test_ranking.py -v` exits 0
- [x] `uv run pytest tests/unit/research/ -v` exits 0 (no regressions)
- [x] `uv run mypy src/csm/research/ranking.py` exits 0
- [x] `uv run ruff check src/csm/research/ranking.py` exits 0
- [x] Percentile ranks in `(0, 1]`
- [x] Quintile counts balanced (~N/5 per date)
- [x] Highest signal → quintile 5, lowest → quintile 1
- [x] NaN symbol excluded from ranking on that date; other dates unaffected
- [x] Tied values share the same rank (method='average' verified)
- [x] Small cross-section (< 5 symbols) handled without raising
- [x] `rank_all()` adds rank/quintile for all numeric, non-fwd-ret features
- [x] MultiIndex validation raises `ValueError` on bad index shape

---

## Completion Notes

All deliverables completed on 2026-04-26.

- Rewrote `CrossSectionalRanker` to match PLAN.md spec: `rank(panel_df, signal_col)` and
  `rank_all(panel_df)`. The old `rank(feature_matrix, date)` composite-z-score API removed.
- Used `rank(method='average', pct=True)` — Spearman-IC consistent (Design Decision 2).
- Added `_assign_quintiles()` helper with two-level fallback for small/tied cross-sections
  (Design Decision 3). Quintile column uses nullable `Int8` to support NaN for excluded symbols.
- Added `_validate_panel()` helper for MultiIndex shape/name validation (Design Decision 6).
- `rank_all()` operates on `select_dtypes(include='number')` columns only (Design Decision 5).
- 9 unit tests written; all 4 PLAN-required cases covered plus 5 edge-case tests.
- No regressions in Phases 2.1–2.4 test suites.

### Issues Encountered

1. **`pd.qcut` label count mismatch on small/tied cross-sections** — `duplicates='drop'` reduces
   the number of bins but does not reduce the label list, causing `ValueError`. Addressed with a
   two-level fallback in `_assign_quintiles()`: first try `labels=False` with index remapping,
   then fall back to all-NaN with a warning.
2. **Percentile range** — documented as `(0, 1]` (not `[0, 1]`) because `rank(pct=True)` computes
   `rank / N`, which cannot produce 0.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Sonnet 4.6)
**Status:** Complete
**Completed:** 2026-04-26
