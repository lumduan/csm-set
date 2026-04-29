# Phase 3.9 — Turnover Control, Volatility Scaling, Sector Neutralisation, Walk-Forward

**Feature:** Backtesting Strategy — Rebalance frequency, exit-floor buffer, vol scaling, sector cap, walk-forward validation
**Branch:** `feature/phase-3-backtesting`
**Created:** 2026-04-29
**Status:** In Progress
**Depends On:** Phase 3.8 Complete

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Implementation Steps](#implementation-steps)
6. [File Changes](#file-changes)
7. [Success Criteria](#success-criteria)
8. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 3.8 delivered volume-aware ADTV, buffer 0.25, and an EMA100 fast-exit overlay. The full backtest run produced:

| Metric | Phase 3.8 Result | Phase 3.8 Target | Gap |
|---|---|---|---|
| CAGR | 12.52% | ≥ Phase 3.7 | ✅ maintained |
| Sharpe | 0.663 | ≥ 0.65 | ✅ |
| Max Drawdown | −31.03% | −20% to −25% | ❌ −6pp too deep |
| Annualised turnover | pending re-run | ≤ 180% | ❓ |
| Win Rate | 43.9% | — | — |
| Rolling Sharpe < 0 | 44.3% of periods | — | needs reduction |

Three gaps motivate Phase 3.9:

| Issue | Current State | Target |
|---|---|---|
| Max drawdown −31% | EMA100 fast-exit overlay insufficient alone | Continuous portfolio vol scaling; DD ≤ −25% |
| Turnover / TC drag | Buffer 0.25 + monthly; no exit floor; fixed frequency | Exit-floor eviction + `rebalance_every_n` to test bimonthly |
| Sector concentration + no OOS validation | No sector weight cap; full in-sample backtest only | Sector cap 35%; walk-forward 5-fold OOS Sharpe |

### Intended Outcome

- Max drawdown ≤ −25% with `vol_scaling_enabled=True`
- Annualised turnover ≤ 120% at `rebalance_every_n=2`
- No single sector > 35% of portfolio at any rebalance date
- OOS Sharpe > 0 across all 5 walk-forward folds — confirms strategy is not overfit
- No CAGR regression > 1pp vs Phase 3.8 baseline

---

## AI Prompt

```
You are tasked with designing and implementing Phase 3.9 of the CSM-SET backtesting project,
focusing on three main areas:

A. Turnover and Transaction Cost Management
- Analyze the current turnover and transaction cost impact (see results/.tmp/03_backtest_analysis.html).
- Experiment with enhanced buffer logic (e.g., require existing holdings to drop further in rank
  before being sold).
- Test less frequent rebalancing (e.g., monthly vs. biweekly) and measure impact on CAGR and
  net returns.

B. Max Drawdown Reduction (Risk Management)
- Implement a market regime filter using SET Index moving averages (e.g., reduce equity exposure
  when SET < EMA200).
- Add volatility scaling to adjust position sizes based on current market volatility.

C. Factor Robustness and Sector Neutralization
- Implement sector neutralization to prevent over-concentration in a single sector during
  momentum surges.
- Plan and execute out-of-sample (OOS) or walk-forward analysis to validate robustness and
  guard against overfitting.

Process:
1. Carefully read docs/plans/phase-3-backtesting/phase3.8_volume_buffer_fast_exit.md and
   results/.tmp/03_backtest_analysis.html to understand the current state and results.
2. Draft a detailed plan for Phase 3.9 in markdown, following the format in
   docs/plans/examples/phase1-sample.md. Save this as
   docs/plans/phase-3-backtesting/phase3.9_turnover_regime_sector.md. Include this prompt in
   the plan.
3. Only begin implementation after the plan is complete.
4. Implement the planned improvements, ensuring:
   - Full type safety and explicit type annotations
   - Async/await for all I/O
   - Pydantic models and validation for all configs/data
   - Comprehensive error handling and logging
   - Tests for all new features and edge cases
   - Documentation updates as needed
5. Update docs/plans/phase-3-backtesting/PLAN.md and the phase plan file with progress notes,
   dates, and any issues encountered.
6. When finished, commit all changes with a structured commit message per project policy.
```

---

## Scope

### In Scope

| # | Change | Files |
|---|---|---|
| 1 | Add 6 new constants: `REBALANCE_EVERY_N`, `EXIT_RANK_FLOOR`, `VOL_LOOKBACK_DAYS`, `VOL_TARGET_ANNUAL`, `VOL_SCALE_CAP`, `SECTOR_MAX_WEIGHT` | `src/csm/config/constants.py` |
| 2 | Add 7 Phase 3.9 fields to `BacktestConfig` | `src/csm/research/backtest.py` |
| 3 | Add `exit_rank_floor` hard eviction to `_apply_buffer_logic()`; wire in `_select_holdings()` | `src/csm/research/backtest.py` |
| 4 | Add `rebalance_every_n` subsampling to `run()` loop; accrue returns without rebalancing on skipped periods | `src/csm/research/backtest.py` |
| 5 | Add `_apply_sector_cap()` method; add `sector_map` param to `run()` | `src/csm/research/backtest.py` |
| 6 | Add `_compute_portfolio_vol()` and `_apply_vol_scaling()` methods; wire into `run()` equity branch | `src/csm/research/backtest.py` |
| 7 | New walk-forward module: `WalkForwardConfig`, `WalkForwardFoldResult`, `WalkForwardResult`, `WalkForwardAnalyzer` | `src/csm/research/walk_forward.py` (new) |
| 8 | Unit tests for all Phase 3.9 changes | `tests/unit/research/test_backtest.py`, `tests/unit/research/test_walk_forward.py` (new) |
| 9 | Notebook Sections 9 and 10 (Thai markdown) | `notebooks/03_backtest_analysis.ipynb` |
| 10 | Docs update | `docs/plans/phase-3-backtesting/PLAN.md`, this file |

### Out of Scope

- Replacing EMA200 as the BULL/BEAR regime gate (kept from Phase 3.6)
- Per-stock ATR trailing stop (deferred from Phase 3.7)
- Short-leg / long-short backtest
- Live data refresh or API endpoints
- Min-variance or vol-target weight schemes (already implemented; not changed here)

---

## Design Decisions

### D1 — `rebalance_every_n` as a date subsampler, not a new schedule

**Decision:** Rather than changing `REBALANCE_FREQ` or the pipeline's rebalance schedule, add an integer `rebalance_every_n` to `BacktestConfig`. In `run()`, enumerate the existing monthly rebalance date pairs with an index (`enumerate(zip(dates[:-1], dates[1:]))`). On periods where `period_index % config.rebalance_every_n != 0`, skip the portfolio selection step and instead accrue returns at current weights (zero turnover). The NAV is still updated every period so the equity curve remains monthly.

**Why:** Changing the pipeline schedule would require re-running `FeaturePipeline.build()` with a new date list — which may not be available at backtest time. Subsampling the existing monthly dates at backtest time is fully backward-compatible: existing callers with `rebalance_every_n=1` (default) see no change.

### D2 — Exit-floor as a percentile rank threshold

**Decision:** Extend `_apply_buffer_logic()` with a new `exit_rank_floor: float` parameter (default 0.35). In the holdings-retention loop, after computing `current_rank`, add:

```python
if current_rank < exit_rank_floor:
    continue  # evict unconditionally — bottom of the universe, no buffer protection
```

The floor is applied before the replacement-quality buffer check, so a stock in the bottom 35% is always evicted even if no replacement ranks 0.25+ percentile points higher.

**Why overlay, not replace:** The existing buffer (0.25) protects mid-rank names from spurious churn. The floor targets names that have genuinely fallen to the bottom of the universe — they should not need a buffer to justify eviction.

**Alternative considered:** Reduce buffer threshold further (e.g., 0.20). Rejected — Phase 3.7 sweep showed turnover increases sharply below 0.25 with minimal CAGR gain.

### D3 — Sector cap via equal-weight fraction arithmetic

**Decision:** `_apply_sector_cap(selected, cross_section, sector_map, max_weight)` uses equal-weight arithmetic: sector fraction = `n_sector / len(selected)`. When a sector exceeds `max_weight` (0.35), drop the lowest-ranked stocks in that sector (by composite z-score) until the fraction is ≤ the cap. Re-ranking of other sectors is not needed — the drop reduces sector fraction monotonically.

**Why equal-weight:** The backtest defaults to equal-weight. Non-equal-weight schemes (vol-target, min-variance) produce different sector fractions, but these are uncommon in production runs. Using equal-weight for the cap computation keeps the logic simple and ensures it is always conservative.

**sector_map is optional:** When `None`, the cap method is skipped entirely with no log noise. Callers that do not have sector metadata retain full backward compatibility.

### D4 — Continuous portfolio vol scaling (not a binary regime gate)

**Decision:** After the Phase 3.8 equity-fraction logic, compute the annualised daily return std of the equal-weight portfolio over the last `vol_lookback_days=63` bars. Scale:

```
vol_scale = clamp(vol_target_annual / realized_vol, lower=0.0, upper=vol_scale_cap)
equity_fraction = min(equity_fraction * vol_scale, 1.0)
```

`vol_scale_cap=1.5` allows modest position increase in low-vol regimes, but capped at 1.0 (no leverage). If fewer than 21 bars of price history are available, skip scaling (return `equity_fraction` unchanged).

**Enabled via `vol_scaling_enabled=False` (default off):** The Phase 3.8 baseline is preserved by default. The notebook sweep in Section 9 will show its impact.

**Why portfolio vol, not single-stock vol:** Portfolio vol already reflects sector concentration and correlation. Using stock-level vol would require averaging, which underestimates correlated drawdowns.

### D5 — Expanding-window walk-forward (not k-fold)

**Decision:** `WalkForwardAnalyzer` uses expanding windows: fold i has train [start, fold_cutoff_i] and test [fold_cutoff_i, fold_cutoff_i + test_years]. Cutoffs are evenly spaced across the date range such that all folds have at least `min_train_years` of training data.

**Why expanding:** Rolling windows (fixed train size) waste data. The momentum strategy does not have a strong recency bias in its parameters, so additional training years never hurt. Expanding windows also mirror how a practitioner would have used the strategy in real time.

---

## Implementation Steps

### Step 1 — Constants

**File:** `src/csm/config/constants.py`
- Add after `EXIT_EMA_WINDOW`:
  - `REBALANCE_EVERY_N: int = 1` — default monthly (no change)
  - `EXIT_RANK_FLOOR: float = 0.35` — evict holdings ranked in the bottom 35% of the universe unconditionally
  - `VOL_LOOKBACK_DAYS: int = 63` — 63-day trailing window for portfolio vol estimation
  - `VOL_TARGET_ANNUAL: float = 0.15` — target annual portfolio volatility (15%)
  - `VOL_SCALE_CAP: float = 1.5` — maximum vol scaling multiplier (no leverage: capped at 1.0 in equity branch)
  - `SECTOR_MAX_WEIGHT: float = 0.35` — max equal-weight fraction for any single sector
- Extend `__all__` with all 6 new names.

### Step 2 — BacktestConfig fields

**File:** `src/csm/research/backtest.py`
- Import the 6 new constants.
- Add `# Phase 3.9 improvements` comment block to `BacktestConfig`:
  - `rebalance_every_n: int = Field(default=REBALANCE_EVERY_N)` — 1=monthly, 2=bimonthly, 3=quarterly
  - `exit_rank_floor: float = Field(default=EXIT_RANK_FLOOR)` — hard eviction below this percentile rank
  - `vol_scaling_enabled: bool = Field(default=False)` — off by default to preserve Phase 3.8 baseline
  - `vol_lookback_days: int = Field(default=VOL_LOOKBACK_DAYS)`
  - `vol_target_annual: float = Field(default=VOL_TARGET_ANNUAL)`
  - `vol_scale_cap: float = Field(default=VOL_SCALE_CAP)`
  - `sector_max_weight: float = Field(default=SECTOR_MAX_WEIGHT)`

### Step 3 — Exit-floor in buffer logic

**File:** `src/csm/research/backtest.py`
- Modify `_apply_buffer_logic(self, current_holdings, candidates, cross_section, buffer_threshold, exit_rank_floor)`:
  - In the retention loop for each `sym in current_holdings`, add:
    ```python
    if current_rank < exit_rank_floor:
        continue  # unconditional eviction — bottom of universe
    ```
  - Update call-site in `_select_holdings()` to pass `config.exit_rank_floor`.

### Step 4 — Rebalance frequency subsampling

**File:** `src/csm/research/backtest.py` — `run()` method
- Change the loop from `for current_date, next_date in zip(...)` to `for rebalance_idx, (current_date, next_date) in enumerate(zip(...))`.
- On skipped periods (`rebalance_idx % config.rebalance_every_n != 0`):
  - Compute `gross_return` at `current_weights` (reindex current holdings into prices window).
  - Update NAV and equity_curve. Append period_report with zero turnover and existing holdings.
  - `continue` — skip the selection, weighting, and cost steps.

### Step 5 — Sector cap

**File:** `src/csm/research/backtest.py`
- Add `_apply_sector_cap(self, selected, cross_section, sector_map, max_weight) -> list[str]`:
  1. If `sector_map` is None or `selected` is empty, return `selected` unchanged.
  2. Compute composite score for ranking within sector: `composite = cross_section.mean(axis=1)`.
  3. Group `selected` by sector. For each sector where `n / len(selected) > max_weight`, drop the lowest-composite stocks until the cap is met.
  4. Return pruned list (preserving original order for non-capped symbols).
- Modify `run()` signature: add `sector_map: dict[str, str] | None = None`.
- After `selected = self._select_holdings(...)` and before weight construction:
  ```python
  if sector_map is not None:
      selected = self._apply_sector_cap(selected, cross_section, sector_map, config.sector_max_weight)
  if not selected:
      continue
  ```

### Step 6 — Portfolio vol scaling

**File:** `src/csm/research/backtest.py`
- Add `_compute_portfolio_vol(self, prices, holdings, asof, lookback_days) -> float`:
  - Slice `prices[holdings]` to the last `lookback_days` calendar bars ending at `asof`.
  - Compute equal-weight daily returns; annualise as `std * sqrt(252)`.
  - Return `float("nan")` when fewer than 21 bars are available.
- Add `_apply_vol_scaling(self, prices, holdings, asof, equity_fraction, lookback_days, vol_target, vol_scale_cap) -> float`:
  - Calls `_compute_portfolio_vol()`; skips scaling on `nan`.
  - Returns `min(equity_fraction * clamp(vol_target / realized_vol, 0, vol_scale_cap), 1.0)`.
- In `run()`, after the equity-fraction logic block (Phase 3.8), add:
  ```python
  if config.vol_scaling_enabled and equity_fraction > 0.0 and len(current_holdings) > 0:
      equity_fraction = self._apply_vol_scaling(
          prices, current_holdings, current_date, equity_fraction,
          config.vol_lookback_days, config.vol_target_annual, config.vol_scale_cap,
      )
  ```

### Step 7 — Walk-forward module

**New file:** `src/csm/research/walk_forward.py`

```python
class WalkForwardConfig(BaseModel):
    n_folds: int = Field(default=5)
    test_years: int = Field(default=1)
    min_train_years: int = Field(default=5)

class WalkForwardFoldResult(BaseModel):
    fold: int
    train_start: str
    train_end: str   # exclusive cutoff
    test_start: str
    test_end: str
    oos_metrics: dict[str, float]

class WalkForwardResult(BaseModel):
    folds: list[WalkForwardFoldResult]
    aggregate_oos_metrics: dict[str, float]
    is_vs_oos_sharpe: float   # full_IS_sharpe / mean_OOS_sharpe
    is_metrics: dict[str, float]

class WalkForwardAnalyzer:
    def run(
        self,
        feature_panel: pd.DataFrame,
        prices: pd.DataFrame,
        config: BacktestConfig,
        wf_config: WalkForwardConfig,
        *,
        volumes: pd.DataFrame | None = None,
        index_prices: pd.Series | None = None,
        sector_map: dict[str, str] | None = None,
        store: ParquetStore,
    ) -> WalkForwardResult:
        ...
```

Expanding window fold construction: given total dates range `[start, end]`, the test window for fold i starts at `start + min_train_years + i * test_years`. Raises `BacktestError` when insufficient dates exist for at least one fold.

### Step 8 — Tests

**`tests/unit/research/test_backtest.py`** — add 5 new test classes:

- `TestExitFloor`:
  - `test_holdings_below_floor_always_evicted` — holding at rank 0.20 with floor 0.35 → evicted even when no good replacement exists
  - `test_holdings_above_floor_protected_by_buffer` — holding at rank 0.60, best replacement at 0.70 (diff 0.10 < buffer 0.25) → retained
  - `test_floor_zero_disables_hard_eviction` — `exit_rank_floor=0.0` → no unconditional evictions (buffer-only behaviour)

- `TestRebalanceEveryN`:
  - `test_n1_rebalances_every_period` — all periods have turnover > 0 when holdings change each month
  - `test_n2_skips_odd_periods` — turnover is 0.0 on periods with index 1, 3, 5; rebalance on 0, 2, 4
  - `test_nav_still_updates_on_skipped_periods` — equity curve has an entry for every month regardless of n

- `TestSectorCap`:
  - `test_no_sector_map_returns_unchanged` — `sector_map=None` → `_apply_sector_cap` returns input unchanged
  - `test_overweight_sector_trimmed` — 8 of 10 stocks in same sector with max_weight=0.35 → trimmed to 3 (30%)
  - `test_balanced_sectors_not_trimmed` — two sectors at 50% each with max_weight=0.60 → no trimming

- `TestVolScaling`:
  - `test_disabled_returns_equity_fraction_unchanged` — `vol_scaling_enabled=False` → equity_fraction unchanged in run()
  - `test_high_vol_reduces_equity_fraction` — realized vol 0.30 with target 0.15 → fraction halved
  - `test_low_vol_capped_at_scale_cap_then_1` — realized vol 0.05 with target 0.15 → scale = min(3.0, cap=1.5) → fraction * 1.5 capped at 1.0

- `TestPhase39Defaults`:
  - `test_rebalance_every_n_default` — `BacktestConfig().rebalance_every_n == 1`
  - `test_exit_rank_floor_default` — `BacktestConfig().exit_rank_floor == 0.35`
  - `test_vol_scaling_disabled_by_default` — `BacktestConfig().vol_scaling_enabled == False`
  - `test_sector_max_weight_default` — `BacktestConfig().sector_max_weight == 0.35`

**`tests/unit/research/test_walk_forward.py`** — new file with 5 tests.

### Step 9 — Notebook

`notebooks/03_backtest_analysis.ipynb` — append two sections (all markdown in Thai):

- **Section 9 — ความไวต่อพารามิเตอร์ Phase 3.9**: Sweep `rebalance_every_n ∈ {1, 2, 3}` and `vol_scaling_enabled ∈ {True, False}`; table of CAGR, Sharpe, Max DD, annualised turnover.
- **Section 10 — Walk-Forward Analysis**: Run `WalkForwardAnalyzer` with `n_folds=5, test_years=1`; bar chart of per-fold OOS Sharpe; IS vs OOS Sharpe comparison table.

### Step 10 — Docs

- Update `docs/plans/phase-3-backtesting/PLAN.md` with Phase 3.9 status row and implementation notes.

---

## File Changes Summary

| File | Change | Est. LoC |
|---|---|---|
| `src/csm/config/constants.py` | +6 constants, extend `__all__` | +14 / 0 |
| `src/csm/research/backtest.py` | +7 config fields; exit-floor; rebalance_every_n; sector_map param; `_apply_sector_cap()`; `_compute_portfolio_vol()`; `_apply_vol_scaling()`; wire into `run()` | +120 / −5 |
| `src/csm/research/walk_forward.py` | New file | +200 |
| `tests/unit/research/test_backtest.py` | +5 new test classes, ~14 tests | +220 |
| `tests/unit/research/test_walk_forward.py` | New file, ~5 tests | +150 |
| `notebooks/03_backtest_analysis.ipynb` | +2 sections (Sections 9–10) | ~5 cells |
| `docs/plans/phase-3-backtesting/phase3.9_turnover_regime_sector.md` | New file (this document) | new |
| `docs/plans/phase-3-backtesting/PLAN.md` | +Phase 3.9 row + notes | ~20 |

---

## Success Criteria

| Criterion | Target | Verification |
|---|---|---|
| Max drawdown with `vol_scaling_enabled=True` | ≤ −25% | Notebook Section 9 sweep |
| Annualised turnover at `rebalance_every_n=2` | ≤ 120% | Notebook `period_summary()` table |
| Sector weight cap fires on overweight sector | Single sector ≤ 35% | Unit test `TestSectorCap` + notebook holdings |
| CAGR regression vs Phase 3.8 (baseline config) | ≤ −1.0pp | Record before/after metrics |
| Sharpe regression vs Phase 3.8 (baseline config) | ≤ −0.05 | Record before/after metrics |
| OOS Sharpe > 0 in walk-forward | All 5 folds | Section 10 bar chart |
| All unit + integration tests pass | exit code 0 | `uv run pytest tests/` |
| Type checking clean | exit code 0 | `uv run mypy src/` |
| Ruff clean | exit code 0 | `uv run ruff check src/ && uv run ruff format --check src/` |
| `BacktestConfig()` defaults match constants | Static assertions | `TestPhase39Defaults` |

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|---|---|---|
| Sector cap trims portfolio below `n_holdings_min` | Low | `_apply_sector_cap` only removes stocks; `_select_holdings` already ensures minimum; add guard to skip cap when selected would fall below `n_holdings_min` |
| Vol scaling introduces whipsaw at low-vol regime boundaries | Medium | `vol_scale_cap=1.5` limits upside; cap at 1.0 prevents leverage; if CAGR regression > 1pp, tune `vol_target_annual` upward |
| Walk-forward folds have too few dates for meaningful backtest | Medium | `min_train_years=5` check; raise `BacktestError` with descriptive message when insufficient; default 5-year train + 1-year test requires ≥ 6 years of data |
| Rebalance skip period return uses stale weights | Low | `current_weights` Series is carried over from last rebalance; `.reindex(prices.columns).fillna(0.0)` handles dropped symbols conservatively |

---

## Critical Files

- `src/csm/research/backtest.py:128–153` — BacktestConfig (add Phase 3.9 fields)
- `src/csm/research/backtest.py:236–275` — `_apply_buffer_logic()` (add exit_rank_floor parameter)
- `src/csm/research/backtest.py:277–317` — `_select_holdings()` (pass exit_rank_floor)
- `src/csm/research/backtest.py:464–630` — `run()` loop (rebalance_every_n, sector_map, vol scaling)
- `src/csm/config/constants.py` — 6 new constants
- `src/csm/research/walk_forward.py` — new module
- `tests/unit/research/test_backtest.py` — 5 new test classes
- `tests/unit/research/test_walk_forward.py` — new file

---

## Completion Notes

- **Date completed:** TBD
- **Final metrics (vs Phase 3.8):** Pending notebook re-run
- **Issues encountered:** TBD
- **Test count delta:** TBD
- **Commit SHA:** Pending
