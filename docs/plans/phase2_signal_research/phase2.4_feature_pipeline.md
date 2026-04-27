# Phase 2.4 - Feature Pipeline

**Feature:** Assemble cross-sectional panel DataFrame with winsorization, z-scoring, sector integration, and forward return computation
**Branch:** `feature/phase-2-signal-research`
**Created:** 2026-04-25
**Status:** Complete — 2026-04-25
**Depends On:** Phase 2.1 (MomentumFeatures), Phase 2.2 (RiskAdjustedFeatures), Phase 2.3 (SectorFeatures)

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

Phase 2.4 extends `FeaturePipeline` — the orchestration layer that assembles all individual feature
computations (2.1–2.3) into a single cross-sectional panel DataFrame ready for IC analysis and
ranking in Phases 2.5–2.6.

The existing `pipeline.py` already implements the core z-scoring and winsorization loop for
MomentumFeatures and RiskAdjustedFeatures. Phase 2.4 adds:

1. **SectorFeatures integration** — equal-weight sector index construction and per-symbol
   `sector_rel_strength` computation.
2. **float32 casting** — feature columns are cast to `float32` after normalization to save memory
   on a panel that can reach ~50 K rows.
3. **Dropped-symbol logging** — the count of symbols dropped per date due to NaN features is
   logged at INFO level for auditability.
4. **`build_forward_returns()`** — computes forward log returns for each horizon (1M, 2M, 3M,
   6M, 12M) and joins them to the panel DataFrame as `fwd_ret_{h}m` columns (float32).

### Parent Plan Reference

- `docs/plans/phase2_signal_research/PLAN.md`

### Key Deliverables

1. `src/csm/features/pipeline.py` — updated `FeaturePipeline` with sector integration,
   float32 output, dropped-symbol logging, and `build_forward_returns()`
2. `tests/unit/features/test_pipeline.py` — expanded test suite covering all new behaviour

---

## AI Prompt

The following prompt was used to generate this phase:

```text
🎯 Objective
Implement Phase 2.4 - Feature Pipeline for the signal research project by planning, documenting,
and executing the required code and documentation updates, following the provided instructions
and project standards.

📋 Context
- The project is located at /Users/sarat/Code/csm-set.
- The current focus is on Phase 2.4 - Feature Pipeline, as described in
  docs/plans/phase2_signal_research/PLAN.md.
- The previous implementation phase was Phase 2.3 - Sector Features (see
  docs/plans/phase2_signal_research/phase2.3_sector_features.md).
- Documentation and planning must follow the format in docs/plans/examples/phase1-sample.md.
- All work must comply with the project's architectural, documentation, and workflow standards.

🔧 Requirements
- Carefully read and understand docs/plans/phase2_signal_research/PLAN.md, focusing on
  Phase 2.4 - Feature Pipeline.
- Review docs/plans/phase2_signal_research/phase2.3_sector_features.md for context on the
  last completed phase.
- Before coding, create a detailed plan for Phase 2.4 as a markdown file at
  docs/plans/phase2_signal_research/phase2.4_feature_pipeline.md, following the format in
  docs/plans/examples/phase1-sample.md. Include the prompt used for this task in the plan.
- Only begin implementation after the plan is complete.
- Upon completion, update docs/plans/phase2_signal_research/PLAN.md and
  docs/plans/phase2_signal_research/phase2.4_feature_pipeline.md with progress notes,
  completion dates, and any issues encountered.
- Ensure all code and documentation changes follow the project's core architectural principles,
  documentation standards, and workflow requirements.
- Commit all changes when the job is finished.
```

---

## Scope

### In Scope

| Component | Description | Status |
| --- | --- | --- |
| `FeaturePipeline.__init__` | Accept optional `universe_store` and `settings` params | Complete |
| `FeaturePipeline.build()` | Add keyword-only `symbol_sectors`; integrate SectorFeatures | Complete |
| Sector index construction | Equal-weight average of in-prices symbols per sector (include-self) | Complete |
| float32 casting | Feature columns cast to float32 after winsorization + z-score | Complete |
| Dropped-symbol logging | Log count of symbols dropped per date via `logger.info` | Complete |
| Price + date caching | Cache `prices` and `rebalance_dates` after `build()` | Complete |
| `build_forward_returns()` | Compute `fwd_ret_1m` … `fwd_ret_12m` and join to panel | Complete |
| Horizon validation | `ValueError` on empty, non-positive, or duplicate horizons | Complete |
| Panel structure validation | `_validate_panel_df()` checks MultiIndex, names, uniqueness | Complete |
| Union-of-symbols loop | Per-date candidates from all feature families, not just momentum | Complete |
| Unit tests | 20 tests; z-score std, winsorization, NaN drop, float32, sector, fwd returns, drift | Complete |

### Out of Scope

- Universe snapshot loading from `universe_store` (deferred; `build()` still accepts `prices` dict)
- `CrossSectionalRanker` (Phase 2.5)
- `ICAnalyzer` (Phase 2.6)
- Integration tests against real parquet data

### Existing API Preserved

The existing `build(prices, rebalance_dates)` call sites continue to work; `symbol_sectors` is
keyword-only with a default of `None`.

---

## Design Decisions

### 1. Raw pandas types: formal architectural exception to the Pydantic rule

The project rule requires Pydantic models for all validated inputs and outputs. The feature and
pipeline layer is an **explicit, documented exception** to this rule because:

- The entire feature layer (Phases 2.1–2.3) already uses raw pandas types (`pd.Series`,
  `pd.DatetimeIndex`) as the API contract. Introducing Pydantic wrappers here would require
  wrapping every `pd.Series` in a model, which adds boilerplate with no benefit in a research
  pipeline where data comes from trusted internal sources, not external user inputs.
- Each feature `compute()` method is its own validation boundary: it raises `TypeError` if the
  index is not a `DatetimeIndex` and `ValueError` on duplicates. The pipeline delegates to these
  validated boundaries rather than duplicating the validation.
- `FeaturePipeline` is a local, synchronous batch computation class — not an API endpoint. The
  appropriate boundary for Pydantic validation is at the HTTP/CLI surface (Phases 5–6).

**Scope of the exception:** `prices`, `rebalance_dates`, and `symbol_sectors` remain raw Python
types. `horizons` is validated manually inside `build_forward_returns()`.

This exception is scoped to Phase 2 only. Phase 5 will introduce Pydantic request/response
models at the API layer that wrap the pipeline outputs.

### 2. Keep `prices` dict as input to `build()`: documented deviation from PLAN

The PLAN describes `build(rebalance_dates)` loading from store internally. The current
implementation accepts `prices: dict[str, pd.DataFrame]`, which is better for unit testing
(no disk I/O in tests). The optional `universe_store` and `settings` args are added to the
constructor for Phase 2.5+ compatibility, but `build()` keeps the dict API. This deviation
is deliberate and scoped to Phase 2.

### 3. Equal-weight sector index: include-self

The sector index is `mean(axis=1)` of all close Series in the same sector from the `prices`
dict — including the target symbol itself. This slightly dilutes `sector_rel_strength` in
small sectors but avoids leave-one-out complexity. For sectors with ≥ 10 symbols the
self-inclusion effect is < 10 % and acceptable for research. Leave-one-out is deferred to
Phase 9 if empirical IC shows systematic downward bias.

### 4. `symbol_sectors` is keyword-only in `build()`

Using `*` before `symbol_sectors` enforces keyword-only calling at the function boundary,
preventing silent positional-arg mistakes as the signature grows.

### 5. Exception handling: `TypeError | ValueError` only; unexpected errors propagate

Feature `compute()` calls may raise `TypeError` (non-DatetimeIndex) or `ValueError` (duplicate
timestamps). These are caught per-symbol and logged as warnings so one bad symbol does not abort
the entire date's computation. **Unexpected exceptions (`Exception`) are not caught** — they
propagate to the caller, which is the correct fail-fast behaviour for debugging. The previous
broad `except Exception` pattern from the Phase 2.1/2.2 integration is retained in the existing
momentum and risk loops for backwards compatibility, but is not extended to the new sector loop.

### 6. Named parameters in `compute()` calls; logging uses standard `%s` positional style

All calls to feature `compute()` methods use keyword arguments. Python's `logging` module does
not support keyword arguments for message substitution parameters — `logger.warning("msg %s",
value)` is the standard lazy-evaluation pattern required for performance. The named-parameter
rule is therefore scoped to custom function/method calls, not `logging` calls.

### 7. Forward returns anchored to original rebalance calendar

`build_forward_returns()` anchors horizon shifts to `self._last_rebalance_dates` — the list
passed to `build()` — not to `panel_df.index.get_level_values("date").unique()`. If a date was
dropped from the panel (all symbols NaN), using panel dates as anchor shifts all subsequent
horizons, producing wrong forward returns. The original calendar avoids this drift.

### 8. Horizon validation in `build_forward_returns()`

Before computing forward returns, validate `horizons`:

- Must be non-empty: `ValueError("horizons must not be empty")`
- All values must be positive integers (≥ 1): `ValueError("all horizons must be positive integers")`
- No duplicates: `ValueError("horizons must not contain duplicates")`
- Unsorted input is accepted and processed in the order given (column order matches `horizons`).

### 9. Synchronous I/O: same approved exception as `ParquetStore`

`FeaturePipeline.build()` is synchronous. The rationale is identical to `ParquetStore`: pyarrow
read/write and pandas computation over local files are CPU-bound, not I/O-bound. Callers that
need non-blocking execution should wrap in `asyncio.to_thread()`.

### 10. `build_forward_returns()` on an empty panel

When `panel_df` is empty, the method returns a copy of `panel_df` with `fwd_ret_{h}m` columns
added (all NaN, float32). This keeps the schema predictable for downstream code that unconditionally
reads forward-return columns.

### 11. Empty `build()` output schema

When no valid symbols survive on any date, `build()` returns:

```python
pd.DataFrame(index=pd.MultiIndex.from_arrays([[], []], names=["date", "symbol"]))
```

No feature columns are defined (consistent with existing behaviour).

---

## Function Signatures

### `FeaturePipeline`

```python
class FeaturePipeline:

    def __init__(
        self,
        store: ParquetStore,
        universe_store: ParquetStore | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Initialize the pipeline.

        Args:
            store: ParquetStore for persisting/loading the feature panel.
            universe_store: Optional store for universe snapshots. Reserved for
                            Phase 2.5+ when build() will load data internally.
            settings: Optional application settings. Reserved for Phase 2.5+.
        """

    def build(
        self,
        prices: dict[str, pd.DataFrame],
        rebalance_dates: list[pd.Timestamp],
        *,
        symbol_sectors: dict[str, str] | None = None,
    ) -> pd.DataFrame:
        """Build a z-scored, winsorized feature panel across rebalance dates.

        Args:
            prices: Mapping from symbol to OHLCV DataFrames (must have a 'close'
                    column with a DatetimeIndex). Key 'SET:SET' triggers
                    risk-adjusted feature computation.
            rebalance_dates: Ordered list of rebalance timestamps.
            symbol_sectors: (keyword-only) Optional mapping from symbol to sector
                            code (e.g. "BANK"). When provided, sector_rel_strength
                            is computed per symbol. Symbols with no sector peers in
                            prices receive NaN and are dropped by the NaN filter.

        Returns:
            MultiIndex DataFrame with index (date, symbol). Feature columns are
            float32, winsorized at 1st/99th percentile, and z-scored cross-
            sectionally per date. Symbols with NaN in any feature are dropped.
            Returns an empty DataFrame with MultiIndex names ["date", "symbol"]
            and no columns when no valid symbols survive on any date.

        Examples:
            >>> panel = pipeline.build(
            ...     prices=ohlcv_map,
            ...     rebalance_dates=[pd.Timestamp("2023-06-30", tz="Asia/Bangkok")],
            ...     symbol_sectors={"SET:AOT": "SERVICE"},
            ... )
        """

    def build_forward_returns(
        self,
        panel_df: pd.DataFrame,
        horizons: list[int],
        prices: dict[str, pd.DataFrame] | None = None,
    ) -> pd.DataFrame:
        """Compute forward log returns and join them to panel_df.

        Forward returns are anchored to the original rebalance calendar stored
        from the last build() call, not the surviving panel dates, to prevent
        horizon drift when dates are dropped because all symbols were NaN.

        Args:
            panel_df: MultiIndex (date, symbol) panel produced by build().
            horizons: Non-empty list of positive integer horizon numbers in months,
                      e.g. [1, 2, 3, 6, 12]. Duplicates raise ValueError.
                      For horizon h, fwd_ret_{h}m = log(close[t+h] / close[t])
                      where t and t+h are consecutive entries in the original
                      rebalance calendar.
            prices: OHLCV dict keyed by symbol. Defaults to prices from the last
                    build() call when None.

        Returns:
            panel_df extended with float32 columns fwd_ret_{h}m for each h in
            horizons (in the order given). Values are raw log returns, never
            z-scored. NaN when the h-th future rebalance date does not exist in
            the original calendar, or when the close price is missing at either
            anchor date. When panel_df is empty, returns a copy with the forward-
            return columns added (all NaN).

        Raises:
            ValueError: If horizons is empty, contains non-positive values, or
                        contains duplicate values.

        Examples:
            >>> panel_fwd = pipeline.build_forward_returns(
            ...     panel_df=panel,
            ...     horizons=[1, 2, 3, 6, 12],
            ... )
        """

    def load_latest(self) -> pd.DataFrame:
        """Load the latest persisted feature panel from the store."""
```

---

## Implementation Steps

### Step 1 — Update `FeaturePipeline.__init__`

- Add `universe_store: ParquetStore | None = None` and `settings: Settings | None = None`.
- Add `self._sector: SectorFeatures = SectorFeatures()`.
- Add `self._last_prices: dict[str, pd.DataFrame] = {}`.
- Add `self._last_rebalance_dates: list[pd.Timestamp] = []`.

### Step 2 — Add keyword-only `symbol_sectors` and build sector indices

```python
def build(
    self,
    prices: dict[str, pd.DataFrame],
    rebalance_dates: list[pd.Timestamp],
    *,
    symbol_sectors: dict[str, str] | None = None,
) -> pd.DataFrame:
```

When `symbol_sectors` is not None, build equal-weight sector indices:

```python
sector_series_map: dict[str, list[pd.Series]] = {}
for sym, frame in prices.items():
    if sym == _INDEX_SYMBOL or sym not in symbol_sectors:
        continue
    code = symbol_sectors[sym]
    sector_series_map.setdefault(code, []).append(frame["close"])

sector_index_closes: dict[str, pd.Series] = {
    code: pd.concat(series_list, axis=1).mean(axis=1)
    for code, series_list in sector_series_map.items()
}
```

### Step 3 — Compute sector features per symbol (narrow exceptions, named params)

```python
symbol_sector_feats: dict[str, pd.DataFrame] = {}
if symbol_sectors and sector_index_closes:
    for sym, frame in prices.items():
        if sym == _INDEX_SYMBOL or sym not in symbol_sectors:
            continue
        series: pd.Series = frame["close"].rename(sym)
        try:
            sector_df: pd.DataFrame = self._sector.compute(
                symbol_close=series,
                sector_closes=sector_index_closes,
                symbol_sector=symbol_sectors[sym],
                rebalance_dates=dates_index,
            )
            symbol_sector_feats[sym] = sector_df
        except (TypeError, ValueError) as exc:
            logger.warning("Skipping sector features for symbol %s: %s", sym, exc)
```

### Step 4 — Include sector features in per-date row assembly

After momentum and risk feature updates in the date loop:

```python
if symbol in symbol_sector_feats and rebalance_date in symbol_sector_feats[symbol].index:
    row.update(symbol_sector_feats[symbol].loc[rebalance_date].to_dict())
```

### Step 5 — Log dropped symbols and cast to float32

```python
n_before: int = len(feature_frame)
feature_frame = feature_frame.dropna()
n_dropped: int = n_before - len(feature_frame)
if n_dropped > 0:
    logger.info("Dropped %d symbols with NaN features on %s", n_dropped, rebalance_date)
```

After winsorization and z-scoring:

```python
winsorised = winsorised.astype("float32")
```

### Step 6 — Cache prices and rebalance dates at end of `build()`

```python
self._last_prices = prices
self._last_rebalance_dates = list(rebalance_dates)
```

### Step 7 — Implement `build_forward_returns()`

```python
def build_forward_returns(
    self,
    panel_df: pd.DataFrame,
    horizons: list[int],
    prices: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    if not horizons:
        raise ValueError("horizons must not be empty")
    if any(h < 1 for h in horizons):
        raise ValueError("all horizons must be positive integers (>= 1)")
    if len(horizons) != len(set(horizons)):
        raise ValueError("horizons must not contain duplicates")

    _prices = prices if prices is not None else self._last_prices
    rebal_cal: list[pd.Timestamp] = self._last_rebalance_dates
    fwd_cols: list[str] = [f"fwd_ret_{h}m" for h in horizons]

    if panel_df.empty or not _prices or not rebal_cal:
        empty_fwd = pd.DataFrame(
            float("nan"), index=panel_df.index, columns=fwd_cols, dtype="float32"
        )
        return panel_df.join(empty_fwd, how="left")

    n_cal = len(rebal_cal)
    cal_pos: dict[pd.Timestamp, int] = {t: i for i, t in enumerate(rebal_cal)}

    # Close price at each calendar date per symbol
    fwd_rows: list[dict[str, object]] = []
    for symbol, sym_group in panel_df.groupby(level="symbol"):
        if symbol not in _prices:
            continue
        close: pd.Series = _prices[symbol]["close"].sort_index()

        rebal_closes: dict[pd.Timestamp, float] = {}
        for t in rebal_cal:
            hist = close.loc[close.index <= t]
            rebal_closes[t] = float(hist.iloc[-1]) if len(hist) > 0 else float("nan")

        for t in sym_group.index.get_level_values("date"):
            row: dict[str, object] = {"date": t, "symbol": symbol}
            i = cal_pos.get(t, -1)
            p0 = rebal_closes.get(t, float("nan"))
            for h in horizons:
                col = f"fwd_ret_{h}m"
                if i >= 0 and i + h < n_cal:
                    t_future = rebal_cal[i + h]
                    p1 = rebal_closes.get(t_future, float("nan"))
                    if not (np.isnan(p0) or np.isnan(p1) or p0 <= 0.0 or p1 <= 0.0):
                        row[col] = float(np.log(p1 / p0))
                    else:
                        row[col] = float("nan")
                else:
                    row[col] = float("nan")
            fwd_rows.append(row)

    if not fwd_rows:
        empty_fwd = pd.DataFrame(
            float("nan"), index=panel_df.index, columns=fwd_cols, dtype="float32"
        )
        return panel_df.join(empty_fwd, how="left")

    fwd_frame: pd.DataFrame = (
        pd.DataFrame(fwd_rows)
        .set_index(["date", "symbol"])[fwd_cols]
        .astype("float32")
    )
    return panel_df.join(fwd_frame, how="left")
```

---

## Test Plan

### Fixtures

Reuse `sample_ohlcv_map` (100 symbols × 500 trading days from 2022-01-03) from `conftest.py`.

```python
_TZ = "Asia/Bangkok"
_DATES = [
    pd.Timestamp("2023-04-28", tz=_TZ),
    pd.Timestamp("2023-05-31", tz=_TZ),
    pd.Timestamp("2023-06-30", tz=_TZ),
]
```

### Test Case 1 — z-score mean ≈ 0 (existing, kept unchanged)

### Test Case 2 — z-score std ≈ 1 per feature per date

Verify `snapshot[col].std(ddof=0)` is within 1e-4 of 1.0 for every feature column per date.

### Test Case 3 — winsorization clips extreme outliers before z-scoring

Inject one symbol with a single `close` value of 1e9 (far above any other). After pipeline
normalization, the maximum absolute z-score across the cross-section for that date must be ≤ 4.0
(confirms the 99th-percentile clip was applied before z-scoring).

### Test Case 4 — symbol with NaN feature is dropped from that date

Add a symbol with only 10 days of history. Verify it is absent from the panel index on all dates.

### Test Case 5 — feature columns are float32

```python
for col in panel.columns:
    assert panel[col].dtype == np.float32
```

### Test Case 6 — sector_rel_strength in output when symbol_sectors provided

Assign all 100 symbols to sector `"AGRO"` via `symbol_sectors`. Verify `"sector_rel_strength"`
is in `panel.columns`.

### Test Case 7 — `build_forward_returns()` column schema

After `build()` on `_DATES` and `build_forward_returns(horizons=[1, 2])`, verify
`"fwd_ret_1m"` and `"fwd_ret_2m"` are in the output columns.

### Test Case 8 — forward return value is log(future/present) at consecutive rebalance dates

Pick one symbol present on `_DATES[0]` and `_DATES[1]`. Get close at both from OHLCV data.
Expected 1M forward return at `_DATES[0]` = `log(close_at_DATES[1] / close_at_DATES[0])`.
Assert the pipeline value matches within 1e-4.

### Test Case 9 — forward return NaN at last rebalance date for horizon 1

At `_DATES[-1]` there is no `_DATES[-1 + 1]`, so `fwd_ret_1m` must be NaN for all symbols.

### Test Case 10 — empty panel when empty prices dict

```python
panel = FeaturePipeline(store=store).build(prices={}, rebalance_dates=_DATES)
assert isinstance(panel.index, pd.MultiIndex)
assert panel.index.names == ["date", "symbol"]
assert len(panel) == 0
```

### Test Case 11 — forward-return horizon drift prevention

Build a prices dict where one rebalance date produces an empty cross-section (all symbols have
insufficient history on that date). Verify that `build_forward_returns()` still uses the original
3-date calendar for horizon shifting, not the 2-date surviving panel:

1. Build a panel with `_DATES = [date_A, date_B, date_C]` where all symbols are too short on
   `date_A` so the panel has only entries for `date_B` and `date_C`.
2. Call `build_forward_returns(horizons=[1])`.
3. Verify `fwd_ret_1m` at `date_B` uses `date_C` (position 1 in original calendar, not
   position 0 in surviving panel — which would also be `date_C`, so verify the actual value
   equals `log(close_date_C / close_date_B)`, not NaN).
4. Verify `fwd_ret_1m` at `date_C` is NaN (no `date_D` in original calendar).

### Test Case 12 — horizon validation: empty list raises ValueError

```python
with pytest.raises(ValueError, match="horizons must not be empty"):
    pipeline.build_forward_returns(panel_df=panel, horizons=[])
```

### Test Case 13 — horizon validation: non-positive value raises ValueError

```python
with pytest.raises(ValueError, match="positive integers"):
    pipeline.build_forward_returns(panel_df=panel, horizons=[0])
```

### Test Case 14 — horizon validation: duplicate values raise ValueError

```python
with pytest.raises(ValueError, match="duplicates"):
    pipeline.build_forward_returns(panel_df=panel, horizons=[1, 1])
```

### Test Case 15 — `build_forward_returns()` on empty panel adds fwd columns (all NaN)

```python
empty_panel = panel.iloc[:0]  # empty MultiIndex DataFrame
result = pipeline.build_forward_returns(panel_df=empty_panel, horizons=[1])
assert "fwd_ret_1m" in result.columns
assert len(result) == 0
```

---

## File Changes

| File | Action | Notes |
| --- | --- | --- |
| `src/csm/features/pipeline.py` | Modify | Sector integration, float32, logging, `build_forward_returns()` |
| `tests/unit/features/test_pipeline.py` | Modify | Add test cases 2–15 |
| `docs/plans/phase2_signal_research/PLAN.md` | Modify | Mark Phase 2.4 checklist complete |
| `docs/plans/phase2_signal_research/phase2.4_feature_pipeline.md` | Create | This file |

---

## Success Criteria

- [x] `uv run pytest tests/unit/features/test_pipeline.py -v` exits 0
- [x] `uv run pytest tests/unit/features/ -v` exits 0 (no regressions)
- [x] `uv run mypy src/csm/features/pipeline.py` exits 0
- [x] `uv run ruff check src/csm/features/pipeline.py` exits 0
- [x] Feature columns are float32 in the panel output
- [x] `sector_rel_strength` appears when `symbol_sectors` is provided
- [x] `fwd_ret_1m` … `fwd_ret_12m` join correctly; NaN at end of calendar
- [x] Dropped-symbol count logged at INFO level per date
- [x] Forward returns anchored to original rebalance calendar (not surviving panel dates)
- [x] Horizon validation raises `ValueError` on empty, non-positive, and duplicate values
- [x] Empty panel forward returns include fwd columns (all NaN)

---

## Completion Notes

All deliverables completed on 2026-04-25.

- `build()` API preserved: `symbol_sectors` added as keyword-only parameter (enforced by `*`
  in the signature) — no breaking change for existing callers.
- `universe_store` and `settings` added to `__init__` as optional parameters, reserved for
  Phase 2.5.
- Raw types retained as a formal architectural exception to the Pydantic rule (Design Decision 1),
  consistent with the existing feature layer API pattern.
- Exception handling narrowed to `(TypeError, ValueError)` for sector features; unexpected
  errors propagate (Design Decision 5).
- Named parameters used in all `compute()` calls; `%s` positional style used in `logger` calls
  per standard Python logging convention (Design Decision 6).
- Forward returns anchored to `self._last_rebalance_dates` to prevent horizon drift
  (Design Decision 7 + Test Case 11).
- Horizon validation added before computation: empty, non-positive, and duplicate values raise
  `ValueError` (Design Decision 8).
- Empty panel for `build_forward_returns()` returns a copy with fwd columns (all NaN, float32)
  (Design Decision 10).
- Sector index uses include-self equal-weight mean (Design Decision 3). Leave-one-out deferred.
- float32 cast per-date before concatenation to minimise peak memory.
- All 15 test cases pass; no regressions in Phases 2.1–2.3 test suites.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Sonnet 4.6)
**Status:** Complete
**Completed:** 2026-04-25
