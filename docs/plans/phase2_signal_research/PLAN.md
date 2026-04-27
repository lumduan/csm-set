# Phase 2 - Signal Research Master Plan

**Feature:** Momentum Signal Research and IC Analysis on the SET market
**Branch:** `feature/phase-2-signal-research`
**Created:** 2026-04-24
**Status:** In Progress - Starting Phase 2
**Positioning:** Research layer - test and select momentum signals that exhibit real alpha in the Thai equity market before investing time in a backtest for Phase 3

---

## Table of Contents

1. [Overview](#overview)
2. [Problem Statement](#problem-statement)
3. [Design Rationale](#design-rationale)
4. [Architecture](#architecture)
5. [Implementation Phases](#implementation-phases)
6. [Data Models](#data-models)
7. [Error Handling Strategy](#error-handling-strategy)
8. [Testing Strategy](#testing-strategy)
9. [Success Criteria](#success-criteria)
10. [Future Enhancements](#future-enhancements)
11. [Commit & PR Templates](#commit--pr-templates)

---

## Overview

### Purpose

Phase 2 is the **research layer** that takes cleaned OHLCV data from Phase 1, computes momentum features, and tests which signals have genuine predictive power on the SET before spending time building a backtest engine in Phase 3.

Core workflow:

1. Compute multiple momentum features (12-1M, 6-1M, 3-1M, 1-0M, risk-adjusted, sector-relative)
2. Combine features into a panel DataFrame (date x symbol) with winsorization and z-scoring
3. Rank symbols cross-sectionally by percentile and assign quintile labels
4. Measure IC (Information Coefficient) and ICIR for each signal across multiple horizons
5. Select the composite signal that will move forward into Phase 3

### Scope

Phase 2 covers 7 sub-phases in dependency order:

| Sub-phase | Deliverable | Purpose |
| --- | --- | --- |
| 2.1 | Momentum Features | Compute mom_12_1, mom_6_1, mom_3_1, mom_1_0 |
| 2.2 | Risk-Adjusted Features | Compute sharpe_momentum and residual_momentum |
| 2.3 | Sector Features | Compute relative strength vs sector index |
| 2.4 | Feature Pipeline | Combine features + winsorize + z-score cross-sectionally |
| 2.5 | Ranking | Percentile ranks + quintile labels per rebalance date |
| 2.6 | IC Analysis | Pearson IC, Spearman IC, ICIR, decay curves |
| 2.7 | Signal Research Notebook | `02_signal_research.ipynb` - complete analysis + composite signal decision |

**Out of scope for Phase 2:**

- Backtest engine (Phase 3)
- Portfolio construction (Phase 4)
- API or UI work (Phases 5-6)
- Live data refresh or scheduled jobs (Phase 5)

### Dependency on Phase 1

Phase 2 requires the following Phase 1 artifacts:

| Artifact | Source | Used In |
| --- | --- | --- |
| `data/raw/dividends/*.parquet` | Phase 1.8 re-fetch | Return computation in all sub-phases |
| `data/processed/*.parquet` | Phase 1.5 PriceCleaner | Raw returns after gap-fill and winsorization |
| `data/universe/{YYYY-MM-DD}.parquet` | Phase 1.4 UniverseBuilder | Investable universe per rebalance date |
| `data/universe/symbols.json` | Phase 1.4 | List of all candidate symbols |

Phase 2 **does not touch** the raw OHLCV store directly - it reads through `ParquetStore` only, and it **does not create** new data under `data/raw/` or `data/processed/`.

---

## Problem Statement

Before writing a backtest engine, we need to know which signals actually have predictive power on the SET because:

1. **Emerging market dynamics differ** - the SET has a higher share of retail investors, wider bid-ask spreads than developed markets, and sector concentration that differs from US and European momentum literature.
2. **Look-ahead bias is easy to hide** - if momentum calculations include the most recent month or use future information during z-score normalization, IC will be overstated.
3. **Signals can be redundant** - if mom_12_1 and mom_6_1 are highly correlated, combining them may not add alpha and may only increase turnover.
4. **IC decay matters** - a signal that works well at 1M forward return may decay faster or slower than others, which affects the appropriate rebalancing frequency.
5. **A gate criterion is needed** - if ICIR < 0.3 for a signal, it should not be included in the Phase 3 composite score.

---

## Design Rationale

### Cross-Sectional Instead of Time-Series

Phase 2 uses cross-sectional ranking, meaning symbols are ranked against each other within the same universe, rather than time-series momentum, which compares each symbol against its own history, because:

- It naturally reduces market beta exposure.
- It aligns with Jegadeesh-Titman (1993) and Rouwenhorst (1999), which studied momentum in emerging markets.
- It is easier to protect against look-ahead bias because each rebalance date uses only data <= the as-of date.

### Skip the Last Month (Formation Gap)

Every momentum feature uses the pattern `[t-N : t-1M]` instead of `[t-N : t]` to avoid short-term reversal effects that are well known in markets, such as bid-ask bounce and microstructure noise. Without this skip, the signal may look artificially worse in IC tests.

### Z-Score Cross-Sectionally, Not Time-Series

Normalization is performed per rebalance date across the cross-section, not across the time series of each symbol, because:

- It prevents market-regime distribution shifts from leaking into the signal.
- It makes all signals directly comparable on the same scale for composite weighting.

### IC vs Quintile Spread

Phase 2 uses both IC and quintile spread (Q5-Q1) as complementary metrics:

- IC measures signal quality in a statistically robust continuous way.
- Quintile spread measures whether a practical Q5 long / Q1 short portfolio would produce meaningful performance.
- ICIR = mean(IC) / std(IC) measures signal stability across time.

### Panel DataFrame Design

The feature pipeline produces a panel DataFrame indexed by `(date, symbol)` as a MultiIndex. This structure makes it easy to:

- run `groupby` by date for cross-sectional z-scoring,
- join forward returns for multiple horizons directly in pandas,
- export parquet files for Phase 3 consumption.

---

## Architecture

### Directory Layout

```text
src/csm/
├── features/
│   ├── __init__.py
│   ├── momentum.py           # MomentumFeatures - mom_12_1, 6_1, 3_1, 1_0
│   ├── risk_adjusted.py      # RiskAdjustedFeatures - sharpe_momentum, residual_momentum
│   ├── sector.py             # SectorFeatures - relative strength vs sector
│   └── pipeline.py           # FeaturePipeline - combine + winsorise + z-score
├── research/
│   ├── __init__.py
│   ├── ranking.py            # CrossSectionalRanker - percentile rank + quintiles
│   └── ic_analysis.py        # ICAnalyzer - Pearson/Spearman IC, ICIR, decay curves

notebooks/
└── 02_signal_research.ipynb  # IC time series, ICIR table, correlation matrix, decay curves

results/
└── signals/
    └── latest_ranking.json   # exported composite signal scores + quintiles (git-committed)

tests/
└── unit/
  ├── features/
  │   ├── test_momentum.py
  │   ├── test_risk_adjusted.py
  │   ├── test_sector.py
  │   └── test_pipeline.py
  └── research/
    ├── test_ranking.py
    └── test_ic_analysis.py
```

### Dependency Graph

```text
ParquetStore + UniverseBuilder (Phase 1 - read-only)
    ↑ reads
MomentumFeatures       (pandas, numpy - pure computation, no I/O)
RiskAdjustedFeatures   (pandas, numpy, scipy - regression for residual)
SectorFeatures         (pandas - relative to sector aggregation)
    ↑ combined by
FeaturePipeline        (all features -> panel DataFrame; winsorise + z-score)
    ↑ consumed by
CrossSectionalRanker   (percentile rank, quintile labels)
ICAnalyzer             (Pearson/Spearman IC, ICIR, decay)
    ↑ visualized by
02_signal_research.ipynb
```

### Data Flow

```text
data/processed/{SYMBOL}.parquet     <- Phase 1.5 cleaned OHLCV (read-only)
data/universe/{YYYY-MM-DD}.parquet  <- Phase 1.4 universe snapshots (read-only)
    ↓  MomentumFeatures.compute()
    ↓  RiskAdjustedFeatures.compute()
    ↓  SectorFeatures.compute()
    ↓  FeaturePipeline.build()
panel_df: (date, symbol) -> {features}   <- in-memory panel
    ↓  CrossSectionalRanker.rank()
panel_df + {rank, quintile} columns
    ↓  ICAnalyzer.compute_ic()
ic_results: {signal_name -> IC series, ICIR, decay_curve}
    ↓  02_signal_research.ipynb (visualize + decide)
results/signals/latest_ranking.json   <- exported for Phase 5/6 public mode
```

---

## Implementation Phases

### Phase 2.1 - Momentum Features

**Status:** `[x]` Complete — 2026-04-24
**Depends On:** Phase 1.5 (processed OHLCV in `data/processed/`)

**Goal:** Compute the four raw momentum-return variants per symbol and per rebalance date without look-ahead bias.

**Deliverables:**

- [x] `src/csm/features/momentum.py` - `MomentumFeatures`
  - [x] `compute(close: pd.Series, rebalance_dates: pd.DatetimeIndex) -> pd.DataFrame`
    - [x] Input: close price Series for a single symbol and a DatetimeIndex of rebalance dates
    - [x] Output: DataFrame indexed by rebalance dates with signal-name columns
    - [x] `mom_12_1`: return from `t-252` to `t-21` trading days (12 months, skip 1 month)
    - [x] `mom_6_1`: return from `t-126` to `t-21` (6 months, skip 1 month)
    - [x] `mom_3_1`: return from `t-63` to `t-21` (3 months, skip 1 month)
    - [x] `mom_1_0`: return from `t-21` to `t` (1 month, no skip - used as a reversal signal)
    - [x] Returns are computed as `log(price_end / price_start)` for better compositing behavior
    - [x] If the close value at a boundary date is missing -> NaN, with no backfill across the boundary
- [x] Unit test: `mom_12_1` matches a manual pandas calculation
- [x] Unit test: `mom_6_1`, `mom_3_1`, and `mom_1_0` match pandas reference calculations
- [x] Unit test: no look-ahead - the signal at rebalance date `t` uses only closes <= `t-21`
- [x] Unit test: NaN propagation when close history is shorter than the lookback window

**Implementation notes:**

- Use integer offsets in trading days rather than calendar days because the SET closes on public holidays.
- `t-21` ≈ 1 trading month, `t-63` ≈ 3M, `t-126` ≈ 6M, `t-252` ≈ 12M.
- Do not annualize returns - use raw log return for consistency with IC calculation.

---

### Phase 2.2 - Risk-Adjusted Features

**Status:** `[x]` Complete — 2026-04-25
**Depends On:** Phase 2.1 (raw momentum returns), Phase 1 OHLCV data

**Goal:** Build features that adjust returns for risk in order to test whether risk-adjusted signals produce better ICIR than raw momentum.

**Deliverables:**

- [x] `src/csm/features/risk_adjusted.py` - `RiskAdjustedFeatures`
  - [x] `compute(close: pd.Series, index_close: pd.Series, rebalance_dates: pd.DatetimeIndex) -> pd.DataFrame`
    - [x] Input: symbol close, SET index close, rebalance dates
    - [x] Output: DataFrame indexed by rebalance dates with signal-name columns
    - [x] `sharpe_momentum`: `mom_12_1 / vol_12`, where `vol_12` is the annualised std of 252 daily log-returns ending at `t-21` (window `hist.iloc[-274:-21]`)
    - [x] `residual_momentum`: OLS intercept × 252 from regression of symbol vs SET index over the same 252-return window
    - [x] `min_hist = 274` (252 returns + 21-day skip + 1 boundary price)
- [x] Unit test: `sharpe_momentum` remains bounded and does not become infinity when vol != 0
- [x] Unit test: `residual_momentum` recovers known alpha from synthetic data (zero-mean index returns, tolerance 0.06 annualised)
- [x] Unit test: NaN when vol = 0 or history is too short for regression
- [x] Unit test: no look-ahead - mutating skip region (t-20..t) leaves both signals unchanged
- [x] Unit test: NaN when index has too many gaps (< 63 aligned return pairs)
- [x] Unit test: TypeError/ValueError on invalid inputs (19 test cases total)

**Implementation notes:**

- `vol_12` uses `ddof=1` (sample std). NaN when not finite (zero or nan) rather than returning inf.
- `residual_momentum` uses `scipy.stats.linregress`. NaN when `std(index_rets, ddof=1) == 0`.
- `min_hist = 274` (not 253) because 252 daily returns + 21-day skip = 274 prices needed.
- Index close is loaded from `data/processed/SET%3ASET.parquet` (tvkit format).
- `pipeline.py` updated to call `compute()` per-symbol when `SET:SET` key is in prices dict.

---

### Phase 2.3 - Sector Features

**Status:** `[x]` Complete — 2026-04-25
**Depends On:** Phase 1 OHLCV data, `src/csm/config/constants.py` (`SET_SECTOR_CODES`)

**Goal:** Measure each symbol's relative strength versus its own sector index, because momentum on the SET may be more sector-driven than stock-specific.

**Deliverables:**

- [x] `src/csm/features/sector.py` - `SectorFeatures`
  - [x] `compute(symbol_close: pd.Series, sector_closes: dict[str, pd.Series], symbol_sector: str, rebalance_dates: pd.DatetimeIndex) -> pd.DataFrame`
    - [x] Input: symbol close, dict of sector index closes, the symbol's sector code, rebalance dates
    - [x] Output: DataFrame indexed by rebalance dates with column `["sector_rel_strength"]`
    - [x] `sector_rel_strength`: `mom_12_1(symbol) - mom_12_1(sector_index)` - symbol excess return vs its sector over 12 months with a 1-month skip
    - [x] If sector index data is unavailable -> NaN, with no fallback to market data
- [x] Unit test: `sector_rel_strength == 0` when symbol close equals the sector index
- [x] Unit test: positive when the symbol outperforms the sector and negative when it underperforms
- [x] Unit test: NaN when sector data is missing
- [x] Unit test: no look-ahead - uses only data <= `t-21`

**Implementation notes:**

- The sector index is built as the equal-weight average of symbols in that sector passing the universe filter on that date - not the official SET sector index, because clear sector-index data may not be available from tvkit.
- `SET_SECTOR_CODES` in `constants.py` is used as the mapping, but each symbol must also have `sector` metadata loaded from settfex or maintained explicitly.
- `_MIN_HIST = 253`: 253 prices give valid `iloc[-22]` (t-21) and `iloc[-253]` (t-252), consistent with Phase 2.1 offsets.
- `pipeline.py` integration deferred to Phase 2.4; the new `compute()` API is pipeline-ready.
- 17 unit tests covering: schema, zero/positive/negative cases, NaN propagation, look-ahead guard, manual calculation verification, boundary price validation, and all TypeError/ValueError paths.

---

### Phase 2.4 - Feature Pipeline

**Status:** `[x]` Complete — 2026-04-25
**Depends On:** Phases 2.1, 2.2, 2.3

**Goal:** Combine all features into a panel DataFrame ready for IC analysis and ranking, with correct cross-sectional normalization.

**Deliverables:**

- [x] `src/csm/features/pipeline.py` - `FeaturePipeline`
  - [x] `__init__(self, store: ParquetStore, universe_store: ParquetStore | None = None, settings: Settings | None = None)`
  - [x] `build(prices, rebalance_dates, *, symbol_sectors=None) -> pd.DataFrame`
    - [x] Output: MultiIndex DataFrame `(date, symbol)` -> columns = all feature names
    - [x] For each rebalance date:
      1. Candidate symbols from union of all feature families (not just momentum)
      2. Assemble cross-section reindexed to global expected schema
      3. Winsorize each feature column at the 1st and 99th cross-sectional percentiles
      4. Z-score normalize each feature column cross-sectionally (mean 0, std 1)
    - [x] Symbols with NaN in any feature are dropped from that date's panel - no imputation
    - [x] Sector features integrated: equal-weight sector index built from prices dict
    - [x] Feature columns cast to float32 after normalization
    - [x] Dropped-symbol count logged at INFO per date
    - [x] Prices and rebalance dates cached as immutable snapshots after build()
    - [x] Empty result persisted to store so load_latest() does not return stale data
  - [x] `build_forward_returns(panel_df, horizons, prices=None, rebalance_dates=None) -> pd.DataFrame`
    - [x] Compute forward log return per symbol and date for each horizon (1M, 2M, 3M, 6M, 12M)
    - [x] Anchored to original rebalance calendar (not surviving panel dates) to prevent horizon drift
    - [x] Join to `panel_df` with a left join - NaN when horizon data is not yet available
    - [x] Safe for repeat calls: existing fwd_ret_* columns dropped and recomputed
    - [x] Validates: MultiIndex structure, panel dates ⊆ calendar, panel symbols ⊆ prices
  - [x] Input validation: `_validate_prices()`, `_validate_rebalance_dates()`, `_validate_panel_df()`
- [x] Unit test: z-score mean ≈ 0 and std ≈ 1 per date and per feature
- [x] Unit test: winsorization reduces extreme outliers before z-scoring
- [x] Unit test: a symbol with a NaN feature is dropped from that date's output
- [x] Unit test: feature columns are float32
- [x] Unit test: sector_rel_strength in output when symbol_sectors provided
- [x] Unit test: forward return columns present with correct values
- [x] Unit test: forward return NaN at last rebalance date
- [x] Unit test: forward return horizon drift prevention (middle date dropped from panel)
- [x] Unit test: validation errors for bad horizons, bad panel structure, missing dates/symbols

**Implementation notes:**

- `build()` is synchronous - if it is slow, the caller should wrap it in `asyncio.to_thread()`.
- `symbol_sectors` is keyword-only (enforced by `*` in signature).
- Per-date candidate symbols drawn from union of all feature families; reindexed to global schema before dropna().
- `build_forward_returns()` uses `rebalance_dates` param or cached calendar; raises ValueError on no cache.
- Raw pandas types retained as formal architectural exception for the research layer (documented in phase2.4 plan).
- 20 unit tests in test_pipeline.py; 71 total in features/ suite; 0 regressions.

---

### Phase 2.5 - Ranking

**Status:** `[x]` Complete — 2026-04-26
**Depends On:** Phase 2.4 (panel DataFrame)

**Goal:** Create cross-sectional ranks and quintile labels per rebalance date for use in IC analysis and quintile spread analysis.

**Deliverables:**

- [x] `src/csm/research/ranking.py` - `CrossSectionalRanker`
  - [x] `rank(panel_df: pd.DataFrame, signal_col: str) -> pd.DataFrame`
    - [x] Input: `panel_df` with MultiIndex `(date, symbol)` and the name of the composite signal column
    - [x] Output: original `panel_df` plus columns `{signal_col}_rank` (0-1 percentile) and `{signal_col}_quintile` (1-5)
    - [x] Percentile rank per date: `rank(pct=True, method='average')` within each date group
    - [x] Quintile: `pd.qcut(rank, q=5, labels=[1,2,3,4,5], duplicates='drop')` per date with fallback for small cross-sections
  - [x] `rank_all(panel_df: pd.DataFrame) -> pd.DataFrame`
    - [x] Apply `rank()` to every numeric feature column in `panel_df` (skips `fwd_ret_*` and already-ranked columns)
    - [x] Return `panel_df` with rank and quintile columns for all features; one shared copy (no per-column copies)
- [x] Unit test: percentile ranks are in (0, 1]
- [x] Unit test: quintile counts are balanced per date, with each quintile containing approximately `N/5` symbols
- [x] Unit test: highest signal value -> quintile 5, lowest -> quintile 1
- [x] Unit test: symbols with NaN in the signal are dropped from ranking on that date
- [x] Unit test: tied values share the exact average rank (method='average' verified)
- [x] Unit test: small cross-section (< 5 symbols) uses fallback labels without raising
- [x] Unit test: MultiIndex validation (TypeError, flat index, wrong names)
- [x] Unit test: copy semantics — input frame unchanged after rank()
- [x] Unit test: rank\_all() skips fwd\_ret\_\*, existing \_rank/\_quintile, and non-numeric columns

**Implementation notes:**

- Use `rank(method='average')` for ties to stay consistent with Spearman IC.
- Quintile labels are integers (1-5), not strings, for easier filtering in Phase 3.
- `_assign_quintiles()` has a two-level fallback: labels=False with index remapping, then all-NaN with warning.
- `_rank_inplace()` internal helper avoids per-column DataFrame copies in `rank_all()`.
- 15 unit tests in `tests/unit/research/test_ranking.py`; 0 regressions.

---

### Phase 2.6 - IC Analysis

**Status:** `[x]` Complete — 2026-04-27
**Depends On:** Phase 2.4 (panel + forward returns), Phase 2.5 (ranking)

**Goal:** Measure the predictive power of each signal and the composite score using IC, in order to decide which signals enter the Phase 3 composite.

**Deliverables:**

- [x] `src/csm/research/ic_analysis.py` - `ICAnalyzer`
  - [x] `compute_ic(panel_df: pd.DataFrame, signal_col: str, forward_ret_col: str) -> pd.Series`
    - [x] Input: `panel_df` containing a signal column and a forward return column
    - [x] Output: IC time series indexed by rebalance date, with Pearson IC per date
    - [x] Pearson IC: `corr(signal_t, forward_return_t)` per date as a cross-sectional correlation
    - [x] NaN when fewer than 10 symbols are available on that date
  - [x] `compute_rank_ic(panel_df: pd.DataFrame, signal_col: str, forward_ret_col: str) -> pd.Series`
    - [x] Spearman rank IC, ranking both signal and return before correlation
  - [x] `compute_icir(ic_series: pd.Series) -> float`
    - [x] ICIR = `ic_series.mean() / ic_series.std()`
    - [x] Return `NaN` when `ic_series` has fewer than 12 periods
  - [x] `compute_decay_curve(panel_df: pd.DataFrame, signal_col: str, horizons: list[int]) -> pd.Series`
    - [x] Measure mean IC by horizon: 1M, 2M, 3M, 6M, 12M
    - [x] Output: Series indexed by horizons with mean IC values
  - [x] `summary_table(panel_df: pd.DataFrame, signal_cols: list[str], horizon: int = 1) -> pd.DataFrame`
    - [x] Output table: `signal_name -> {Mean_IC, Std_IC, ICIR, t-stat, % positive IC months}`
- [x] Unit test: IC on known synthetic data with a known exact correlation
- [x] Unit test: ICIR matches a manual mean/std calculation
- [x] Unit test: decay curve returns the correct horizons
- [x] Unit test: NaN when fewer than 10 symbols are present on a date
- [x] Unit test: `summary_table` has the correct columns and shape for `signal_cols`

**Implementation notes:**

- Pearson IC can be sensitive to outliers in cross-sectional returns, so Rank IC should also be used as a core metric.
- `t-stat = ICIR * sqrt(T)`, where `T` is the number of non-NaN IC observations.
- The Phase 2.7 notebook will handle visualization and decision-making - `ICAnalyzer` only computes the numbers.

---

### Phase 2.7 - Signal Research Notebook

**Status:** `[ ]` Not started
**Depends On:** All of Phases 2.1-2.6

**Goal:** Provide human sign-off on which signals achieve ICIR > 0.3 on the SET and define the composite signal for Phase 3.

**Deliverables:**

- [ ] `notebooks/02_signal_research.ipynb`
  - [ ] **Section 1: Data Loading** - load `panel_df` from `FeaturePipeline` plus forward returns
  - [ ] **Section 2: IC Time Series** - plot IC time series for each signal (`mom_12_1`, `mom_6_1`, `mom_3_1`, `mom_1_0`, `sharpe_momentum`, `residual_momentum`, `sector_rel_strength`)
  - [ ] **Section 3: ICIR Summary Table** - rank signals by ICIR with confidence intervals
  - [ ] **Section 4: Signal Correlation Matrix** - heatmap of correlations between signals to check redundancy
  - [ ] **Section 5: IC Decay Curves** - mean IC by horizon for each signal
  - [ ] **Section 6: Quintile Return Spreads** - annual Q5-Q1 return by signal and by year (bar chart)
  - [ ] **Section 7: Composite Signal Design** - explain the selected weighting scheme and the ICIR of the composite
  - [ ] **Section 8: Sign-off** - print PASS/FAIL for each exit criterion
  - [ ] All markdown cells are written in Thai
  - [ ] Final outcome: specify the composite signal formula to be used in Phase 3, with rationale

**Implementation notes:**

- The notebook uses `FeaturePipeline`, `CrossSectionalRanker`, and `ICAnalyzer` directly.
- If `data/processed/` is empty, display `WARNING: DATA NOT AVAILABLE` in each section.
- Export IC analysis outputs as JSON under `results/signals/` for Phases 5 and 6.

---

## Data Models

### Feature Column Convention

| Feature Name | Type | Description |
| --- | --- | --- |
| `mom_12_1` | `float32` | 12-1M log return (skip 1M) |
| `mom_6_1` | `float32` | 6-1M log return (skip 1M) |
| `mom_3_1` | `float32` | 3-1M log return (skip 1M) |
| `mom_1_0` | `float32` | 1M log return (no skip - reversal signal) |
| `sharpe_momentum` | `float32` | `mom_12_1 /` trailing 12M volatility |
| `residual_momentum` | `float32` | Market-beta-adjusted 12M alpha |
| `sector_rel_strength` | `float32` | `symbol mom_12_1 - sector mom_12_1` |

Every feature column in `panel_df` produced by `FeaturePipeline.build()` is winsorized and z-scored.

### Panel DataFrame Schema

```text
Index: MultiIndex [(date: pd.Timestamp, symbol: str), ...]
  - date: rebalance date (last trading day of month, UTC)
  - symbol: tvkit format, e.g. "SET:AOT"

Columns:
  - mom_12_1, mom_6_1, mom_3_1, mom_1_0      float32 (z-scored)
  - sharpe_momentum, residual_momentum        float32 (z-scored)
  - sector_rel_strength                       float32 (z-scored)
  - fwd_ret_1m, fwd_ret_2m, fwd_ret_3m        float32 (log return, not z-scored)
  - fwd_ret_6m, fwd_ret_12m                   float32 (log return, not z-scored)
  - rank_{feature}, quintile_{feature}        float32 / int8 (added by CrossSectionalRanker)
```

### IC Result Schema

```python
@dataclass
class ICResult:
    signal_name: str
    ic_series: pd.Series          # index = rebalance_dates, values = Pearson IC
    rank_ic_series: pd.Series     # Spearman IC
    icir: float
    rank_icir: float
    mean_ic: float
    std_ic: float
    t_stat: float
    pct_positive: float           # fraction of months with IC > 0
    decay_curve: pd.Series        # index = horizons [1,2,3,6,12], values = mean IC
```

---

## Error Handling Strategy

| Scenario | Behavior |
| --- | --- |
| Processed OHLCV missing for a symbol | Log a warning; skip the symbol in the pipeline |
| Universe snapshot missing for a rebalance date | Log a warning; skip the entire date |
| Feature is NaN for a symbol on a date | Drop the symbol from that date's cross-section |
| Fewer than 10 symbols for IC on a date | Return NaN for that date's IC |
| `vol = 0` in `sharpe_momentum` | Return NaN, not `inf` |
| Regression data < 63 days in `residual_momentum` | Return NaN - insufficient data for OLS |
| `public_mode=True` on all operations | Phase 2 is local-data computation only - not affected by public mode |

---

## Testing Strategy

### Coverage Target

Minimum 90% line coverage for all modules under `src/csm/features/` and `src/csm/research/`.

### Mocking Strategy

- Feature tests: use synthetic close Series with exact expected returns - no I/O mocking required.
- Pipeline tests: mock `ParquetStore.load` with synthetic DataFrames.
- IC tests: use synthetic `panel_df` with engineered correlations that yield known IC values.
- No integration tests that require live data in Phase 2.

### Test File Map

| Module | Test file |
| --- | --- |
| `src/csm/features/momentum.py` | `tests/unit/features/test_momentum.py` |
| `src/csm/features/risk_adjusted.py` | `tests/unit/features/test_risk_adjusted.py` |
| `src/csm/features/sector.py` | `tests/unit/features/test_sector.py` |
| `src/csm/features/pipeline.py` | `tests/unit/features/test_pipeline.py` |
| `src/csm/research/ranking.py` | `tests/unit/research/test_ranking.py` |
| `src/csm/research/ic_analysis.py` | `tests/unit/research/test_ic_analysis.py` |

### Key Test Cases

**No look-ahead bias** - the most important test in Phase 2:

```python
# Example: the signal at rebalance_date must not use data after t-21
def test_no_lookahead_mom_12_1():
    # Build a close series where price changes after t-21
    # assert the signal does not change based on prices after t-21
```

**Synthetic IC verification:**

```python
# Build a panel where signal = forward_return + noise
# IC should be high based on the signal/noise ratio
```

---

## Success Criteria

| Criterion | Measure |
| --- | --- |
| At least one signal has ICIR > 0.3 | `ICAnalyzer.compute_icir(ic_series) > 0.3` |
| At least one signal has mean IC > 0.03 | `ic_series.mean() > 0.03` |
| Composite signal ICIR > 0.3 | Defined and tested in notebook Section 7 |
| No look-ahead bias | All unit tests for look-ahead pass |
| Z-score mean ≈ 0, std ≈ 1 per date | `pipeline.py` unit tests |
| All unit tests pass | `uv run pytest tests/ -v -m "not integration"` exits 0 |
| Type checking is clean | `uv run mypy src/` exits 0 |
| Linting is clean | `uv run ruff check src/ scripts/` exits 0 |
| Notebook sign-off | Section 8 prints PASS for every criterion |
| Composite signal documented | Section 7 clearly states formula + weights |

---

## Future Enhancements

- **Fundamental overlay** - in Phase 9, add P/BV and ROE signals from SET SMART into the momentum composite.
- **Foreign flow signal** - add net foreign buy/sell data from the SET website as an additional signal.
- **LightGBM ranking model** - in Phase 9, use ML to learn the optimal feature combination instead of linear weights.
- **Regime-conditional IC** - evaluate IC by market regime (BULL/BEAR/NEUTRAL) for dynamic weighting in Phase 4.
- **Factor decay monitoring** - add a scheduled agent to monitor ICIR monthly after the Phase 5 deployment.

---

## Commit & PR Templates

### Commit Message (Plan - this commit)

```text
plan(signal-research): add master plan for Phase 2 - Signal Research

- Creates docs/plans/phase2_signal_research/PLAN.md
- Covers 7 sub-phases: Momentum Features, Risk-Adjusted Features,
  Sector Features, Feature Pipeline, Ranking, IC Analysis, Research Notebook
- Documents panel DataFrame schema: (date, symbol) MultiIndex
- Specifies IC/ICIR gate criteria: ICIR > 0.3, mean IC > 0.03
- Includes architecture, data models, error handling, test matrix,
  and success criteria

Part of Phase 2 - Signal Research roadmap track.
```

### Commit Message (Phase 2.1)

```text
feat(features): add MomentumFeatures - mom_12_1, 6_1, 3_1, 1_0 (Phase 2.1)

- Log-return computation with formation-period skip (t-21 boundary)
- No look-ahead: all signals use close <= t-21 only
- Unit tests: reference pandas computation, NaN propagation, look-ahead guard
```

### Commit Message (Phases 2.2-2.3)

```text
feat(features): add RiskAdjustedFeatures and SectorFeatures (Phases 2.2-2.3)

- sharpe_momentum: mom_12_1 / trailing vol, NaN on zero vol
- residual_momentum: OLS alpha vs SET index (scipy.stats.linregress)
- sector_rel_strength: symbol vs equal-weight sector momentum
- Unit tests: market-neutrality, bounded sharpe, relative strength direction
```

### Commit Message (Phases 2.4-2.5)

```text
feat(features): add FeaturePipeline and CrossSectionalRanker (Phases 2.4-2.5)

- FeaturePipeline: assemble panel (date, symbol), winsorise + z-score per date
- CrossSectionalRanker: percentile rank + quintile labels per signal per date
- Unit tests: z-score properties, no leakage, rank balance, quintile ordering
```

### Commit Message (Phase 2.6)

```text
feat(research): add ICAnalyzer - Pearson/Spearman IC, ICIR, decay (Phase 2.6)

- compute_ic, compute_rank_ic, compute_icir, compute_decay_curve, summary_table
- Unit tests: synthetic data verification, ICIR formula, NaN guards
```

### Commit Message (Phase 2.7)

```text
feat(notebooks): add signal research notebook 02_signal_research.ipynb (Phase 2.7)

- IC time series, ICIR summary table, correlation matrix, decay curves
- Quintile return spreads Q5-Q1 by year
- Composite signal design and sign-off (Phase 3 gate)
- All markdown cells in Thai
```

### PR Description Template

```markdown
## Summary

- Implements the full signal-research layer for csm-set (Phase 2 of 9)
- `MomentumFeatures` - mom_12_1, 6_1, 3_1, 1_0 with formation-gap skip
- `RiskAdjustedFeatures` - sharpe_momentum, residual_momentum (market-neutral)
- `SectorFeatures` - relative strength vs equal-weight sector index
- `FeaturePipeline` - panel assembly, cross-sectional winsorise + z-score
- `CrossSectionalRanker` - percentile rank + quintile labels
- `ICAnalyzer` - Pearson/Spearman IC, ICIR, decay curves, summary table
- `notebooks/02_signal_research.ipynb` - IC analysis + composite signal decision

## Test plan

- [ ] `uv run pytest tests/ -v -m "not integration"` - all unit tests pass
- [ ] `uv run mypy src/` - exits 0
- [ ] `uv run ruff check src/ scripts/` - exits 0
- [ ] `uv run ruff format --check src/ scripts/` - no changes
- [ ] Manual: run notebook `02_signal_research.ipynb` - Section 8 prints PASS for all criteria
- [ ] Manual: ICIR > 0.3 for at least one signal on SET data
- [ ] Manual: composite signal defined with formula documented in notebook Section 7
```
