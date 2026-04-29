# Phase 3.8 — Volume-Aware ADTV, Buffer 0.25, Fast EMA Exit Overlay

**Feature:** Backtesting Strategy — Restore volume to ADTV filter; commit buffer 0.25; add EMA100 fast-exit overlay
**Branch:** `feature/phase-3-backtesting`
**Created:** 2026-04-28
**Status:** Complete
**Depends On:** Phase 3.7 Complete

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

Phase 3.7 delivered four risk-management improvements (portfolio slimming, soft-penalty / entry-only RS, breadth re-entry, EMA50 fast re-entry, buffer 0.20). After running the full backtest, three issues remain:

| Issue | Current State | Target |
|---|---|---|
| ADTV filter silently disabled | `volumes=None` in all production callers; log warning emitted | Volume matrix threaded from pipeline → backtest |
| Annualised turnover > 180% | `BUFFER_RANK_THRESHOLD = 0.20` (conservative end of tested range) | `0.25` (tested, within band, no material CAGR erosion) |
| Max drawdown / recovery exceed relaxed targets | EMA200-only regime gate; holds 100% equity until decisive break below slow line | EMA100 fast-exit overlay scales to 20% equity earlier |

### Intended Outcome

ADTV filter actually fires; turnover ≤180% annualised; max drawdown −20% to −25% and recovery ≤30 months — without regressing CAGR or Sharpe.

---

## AI Prompt

```
🎯 Objective
Design and implement Phase 3.8 of the SET Cross-Sectional Momentum backtesting workflow,
focusing on three targeted improvements: (1) restoring and validating volume data for accurate
ADTV filtering, (2) committing to a buffer_rank_threshold of 0.25 to ensure annualized turnover
meets the 180% target, and (3) reducing maximum drawdown and recovery duration by testing
faster exit signals (EMA100 or EMA50) for portfolio exits. Deliver a comprehensive plan as a
markdown file, update project documentation, and implement all changes with full test coverage
and documentation.

📋 Context
- Research tool for systematic portfolio management and backtesting on the Thai stock market.
- Phase 3.7 introduced soft penalty scoring, market breadth re-entry, volatility-based exits,
  and portfolio slimming.
- Current issues: unreliable ADTV filter due to missing volume data, turnover still above target,
  and max drawdown/recovery duration exceeding relaxed targets.
- Strict type safety, async-first patterns, Pydantic models, comprehensive testing/documentation.

🔧 Requirements
- Restore and validate volume data so the ADTV filter is accurate.
- Set buffer_rank_threshold to 0.25 in constants and BacktestConfig defaults; turnover ≤180%.
- Replace or supplement the current EMA200 exit signal with a faster EMA (EMA100 or EMA50);
  target max DD −20% to −25% and recovery ≤30 months.
- Update all affected modules, configs, and tests.
- Write a detailed markdown plan at
  docs/plans/phase-3-backtesting/phase3.8_volume_buffer_fast_exit.md, including the full prompt.
- Update docs/plans/phase-3-backtesting/PLAN.md with progress notes.
- Type-safe, async where applicable, Pydantic validation, comprehensive error handling/logging.
- Add/update unit tests for ADTV filtering, buffer logic, and exit signal behavior.

📁 Code Context
- docs/plans/phase-3-backtesting/phase3.7_risk_and_reentry.md
- src/csm/config/constants.py
- src/csm/research/backtest.py
- tests/unit/research/test_backtest.py
- docs/plans/phase-3-backtesting/PLAN.md
- docs/plans/examples/phase1-sample.md

✅ Expected Output
- New markdown plan at docs/plans/phase-3-backtesting/phase3.8_volume_buffer_fast_exit.md
- Updated code: (1) restored/validated volume for ADTV; (2) buffer_rank_threshold = 0.25;
  (3) faster exit signal logic (EMA100/EMA50).
- Updated and passing unit tests.
- Updated documentation and PLAN.md with progress.
- A single commit with all changes following project commit message standards.
```

---

## Scope

### In Scope

| # | Change | Files |
|---|---|---|
| 1 | Cache volume matrix in feature pipeline; thread volumes from raw OHLCV → backtest call-sites | `src/csm/features/pipeline.py`, notebook 03, examples, integration test |
| 2 | Raise `BUFFER_RANK_THRESHOLD` 0.20 → 0.25 in constants and `BacktestConfig` default | `src/csm/config/constants.py`, `src/csm/research/backtest.py` |
| 3 | Add `EXIT_EMA_WINDOW = 100` constant + `exit_ema_window` field on `BacktestConfig` | `src/csm/config/constants.py`, `src/csm/research/backtest.py` |
| 4 | Implement EMA100 fast-exit overlay in `run()` equity logic | `src/csm/research/backtest.py` |
| 5 | Unit tests for volume threading, buffer 0.25, EMA100 fast-exit overlay | `tests/unit/research/test_backtest.py`, `tests/integration/test_backtest_pipeline.py` |
| 6 | Update docs (this plan + PLAN.md status block) | `docs/plans/phase-3-backtesting/` |

### Out of Scope

- Re-tuning portfolio size (40–60 stays)
- Re-tuning fast-re-entry EMA (50 stays)
- Adding ATR/volatility per-stock exits (deferred)
- Replacing EMA200 as the BULL/BEAR regime gate (kept as-is to limit blast radius)
- Refactoring the universe pre-filter at `src/csm/data/universe.py:75–79` (already uses volume correctly)

---

## Design Decisions

### D1 — Volume cache lives in the feature pipeline

The breakage point is `src/csm/features/pipeline.py:273`, where the pipeline caches close prices only:

```python
self._last_close_cache = {sym: frame["close"].copy() for sym, frame in prices.items()}
```

**Decision:** Add a parallel `self._last_volume_cache` that holds `frame["volume"]` series alongside close. Expose `build_volume_matrix() -> pd.DataFrame` that returns the wide volume matrix in the same shape as the close matrix consumed by the backtest.

**Why here:** Every caller (notebook, example, integration test) already calls the feature pipeline. Centralising the volume matrix construction means the three callers each add one line (`volumes=pipeline.build_volume_matrix()`) instead of duplicating reshape logic.

**Alternative considered:** Make each caller build the matrix from the OHLCV map. Rejected — three duplicated reshape blocks; easy to drift.

### D2 — Buffer = 0.25 as the new default

`BUFFER_RANK_THRESHOLD` is currently 0.20 at `src/csm/config/constants.py:48`. It is referenced as the default for `BacktestConfig.buffer_rank_threshold`. Both move to 0.25. No new constant; same field, new value.

The buffer logic in `_apply_buffer_logic()` is unchanged — only the default rises. Existing tests that assert behaviour at a specific buffer value pass the threshold explicitly and will not break.

### D3 — EMA100 fast-exit overlay (not a regime gate)

Keep `EMA_TREND_WINDOW = 200` for BULL/BEAR detection; add a separate `EXIT_EMA_WINDOW = 100` and a corresponding `exit_ema_window` field on `BacktestConfig`. Logic in `run()`:

```
regime = BULL if SET.last > EMA(SET, ema_trend_window) else BEAR
fast_exit_triggered = SET.last < EMA(SET, exit_ema_window)

if regime == BULL and fast_exit_triggered:
    equity_fraction = safe_mode_max_equity   # 0.20
elif regime == BULL:
    equity_fraction = 1.0
else:
    # existing bear-mode logic (dynamic, breadth re-entry, fast re-entry)
    equity_fraction = bear_logic(...)
```

**Why an overlay, not a replacement:**
- Replacing EMA200 with EMA100 would change regime classification, propagating into RS-filter activation, breadth re-entry, and `_has_negative_ema_slope()` semantics — all of which were tuned in Phase 3.6/3.7 against the EMA200 baseline.
- An overlay is one new helper method (`_is_fast_exit()`) and one extra `if` in the equity branch — minimal surface area, easy to A/B by setting `exit_ema_window` to a very large value (e.g. 10_000) to disable.

### D4 — Backwards compatibility

The new field `exit_ema_window` defaults to 100. Existing tests that construct `BacktestConfig(...)` without that field automatically get the new behaviour; tests that asserted "BULL → 1.0 equity" must now also satisfy "SET above EMA100" (they do — the test fixtures use trending-up synthetic prices).

---

## Implementation Steps

### Step 1 — Constants & config field

**File:** `src/csm/config/constants.py`
- Change `BUFFER_RANK_THRESHOLD: float = 0.20` → `0.25`, update docstring noting Phase 3.8 commit.
- Add `EXIT_EMA_WINDOW: int = 100` with Phase 3.8 fast-exit overlay docstring.
- Add `EXIT_EMA_WINDOW` to `__all__`.

**File:** `src/csm/research/backtest.py` (BacktestConfig)
- Import `EXIT_EMA_WINDOW` from constants.
- Add new field: `exit_ema_window: int = Field(default=EXIT_EMA_WINDOW)`.

### Step 2 — Fast-exit helper + run-loop wiring

**File:** `src/csm/research/backtest.py`
- Add private method `_is_fast_exit(self, index_prices, asof, ema_window) -> bool` next to `_is_fast_reentry()`. Returns `not self._regime.is_bull_market(index_prices, asof, window=ema_window)`.
- In `run()` equity-fraction branch, add the BULL-with-fast-exit clause before the unconditional `equity_fraction = 1.0`:

```python
if mode is RegimeState.BULL:
    if self._is_fast_exit(index_prices, current_date, config.exit_ema_window):
        equity_fraction = config.safe_mode_max_equity
    else:
        equity_fraction = 1.0
elif self._is_fast_reentry(...):
    equity_fraction = 1.0
elif ...:
    # existing bear logic
```

### Step 3 — Volume threading via feature pipeline

**File:** `src/csm/features/pipeline.py`
- Add `self._last_volume_cache: dict[str, pd.Series] = {}` to `__init__`.
- At the existing close-cache site, cache volume snapshots for symbols that have a `"volume"` column.
- Add public method `build_volume_matrix(self, exclude=...) -> pd.DataFrame` that pivots `_last_volume_cache` into a wide DataFrame indexed by date with one column per symbol.

**Callers updated:**
1. `notebooks/03_backtest_analysis.ipynb` — build `_vol_wide_bt` via `fp.build_volume_matrix()`; pass `volumes=_vol_wide_bt` to `run()`.
2. `examples/backtest_example.py` — call `pipeline.build_volume_matrix()`; pass to `run()`.
3. `tests/integration/test_backtest_pipeline.py` — build volume matrix from fixture; assert no "volumes not provided" warning.

### Step 4 — Tests

**File:** `tests/unit/research/test_backtest.py`
- New class `TestFastExitOverlay`:
  - `test_fast_exit_engages_when_set_below_ema100_in_bull` — synthetic SET trends down crossing EMA100 but stays above EMA200 → equity scaled to 0.20
  - `test_fast_exit_dormant_when_set_above_both_emas` — trending-up index → equity = 1.0 (regression guard)
  - `test_fast_exit_disabled_via_huge_window_matches_phase37` — `exit_ema_window=10_000` → overlay disabled, full equity
- New class `TestPhase38Defaults`:
  - `test_buffer_threshold_default_is_025` — `BacktestConfig().buffer_rank_threshold == 0.25`
  - `test_exit_ema_window_default_is_100` — `BacktestConfig().exit_ema_window == 100`

**File:** `tests/unit/features/test_pipeline.py`
- `test_build_volume_matrix_returns_wide_frame` — after `build()`, volume matrix is non-empty with expected columns
- `test_build_volume_matrix_empty_before_build` — calling before `build()` returns empty frame

**File:** `tests/integration/test_backtest_pipeline.py`
- Pass `volumes` to `run()`; assert no "volumes not provided" warning in captured logs.

### Step 5 — Docs

**File:** `docs/plans/phase-3-backtesting/phase3.8_volume_buffer_fast_exit.md`
- This file.

**File:** `docs/plans/phase-3-backtesting/PLAN.md`
- Update "Current State" header to Phase 3.8 Complete.
- Add Phase 3.8 row to status table.
- Append Phase 3.8 implementation notes.

---

## File Changes Summary

| File | Change | Est. LoC |
|---|---|---|
| `src/csm/config/constants.py` | Update `BUFFER_RANK_THRESHOLD` 0.20→0.25; add `EXIT_EMA_WINDOW = 100` | +4 / -1 |
| `src/csm/research/backtest.py` | Add `exit_ema_window` field; add `_is_fast_exit()`; wire into `run()` equity branch | +25 / -2 |
| `src/csm/features/pipeline.py` | Add `_last_volume_cache`; add `build_volume_matrix()` | +39 / 0 |
| `notebooks/03_backtest_analysis.ipynb` | Build & pass volumes to backtest via `build_volume_matrix()` | 1 cell replaced |
| `examples/backtest_example.py` | Build & pass volumes | +6 / -2 |
| `tests/unit/research/test_backtest.py` | New `TestFastExitOverlay`; new `TestPhase38Defaults` | +117 / 0 |
| `tests/unit/features/test_pipeline.py` | New volume matrix tests | +31 / 0 |
| `tests/integration/test_backtest_pipeline.py` | Pass volumes; assert ADTV firing | +23 / -7 |
| `docs/plans/phase-3-backtesting/phase3.8_volume_buffer_fast_exit.md` | New file | new |
| `docs/plans/phase-3-backtesting/PLAN.md` | Append 3.8 entry | ~15 |

---

## Success Criteria

| Criterion | Target | Verification |
|---|---|---|
| ADTV filter actually executes in the production notebook run | "volumes not provided" warning absent from notebook log | Read notebook log output after re-running cell |
| `BUFFER_RANK_THRESHOLD` constant is 0.25 | Static read of constants.py | grep |
| `BacktestConfig().buffer_rank_threshold == 0.25` | Default propagated | unit test |
| `BacktestConfig().exit_ema_window == 100` | New field defaults correctly | unit test |
| Fast-exit overlay reduces equity in BULL when SET < EMA100 | `equity_fraction == safe_mode_max_equity` | unit test |
| Annualised turnover ≤ 180% | Backtest result metric | run notebook end-to-end |
| Max drawdown −20% to −25% | Backtest result metric | run notebook end-to-end |
| Recovery duration ≤ 30 months | Backtest result metric | run notebook end-to-end |
| All unit + integration tests pass | exit code 0 | `uv run pytest tests/` |
| No regression in CAGR or Sharpe vs Phase 3.7 baseline | within ±0.5% CAGR, ±0.05 Sharpe | record before/after |

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|---|---|---|
| ADTV filter excludes too many names → ranker has empty cross-section | Low | Threshold of 5M THB has historically retained ~250+ names; existing `_apply_adtv_filter` already returns empty gracefully |
| Fast-exit overlay introduces whipsaw, hurting CAGR | Medium | Counter-test with `exit_ema_window=10_000` proves overlay is the only delta; if regression > 0.5% CAGR tune `exit_ema_window` upward before commit |
| Buffer 0.25 reduces responsiveness, hurts CAGR | Low | Phase 3.7 sweep showed 0.25 within 0.3% of 0.20 CAGR; turnover savings outweigh marginal CAGR loss |
| Notebook cell ordering breaks volume matrix construction | Medium | Build the volume matrix in the same cell that builds the close matrix; share the rebalance-dates input |
| Existing tests break due to new BacktestConfig field | Low | New field is additive with default; only behaviour change is in BULL+below-EMA100 path which most synthetic fixtures avoid |

---

## Critical Files

- `src/csm/research/backtest.py:127-151` — BacktestConfig (add exit_ema_window)
- `src/csm/research/backtest.py:201-231` — `_apply_adtv_filter` (no change, verified)
- `src/csm/research/backtest.py:382-393` — `_is_fast_reentry` (template for `_is_fast_exit`)
- `src/csm/research/backtest.py:514-533` — equity-fraction branch (where overlay slots in)
- `src/csm/config/constants.py:48` — `BUFFER_RANK_THRESHOLD`
- `src/csm/features/pipeline.py:273` — close cache (extended with volume cache)
- `tests/unit/research/test_backtest.py:193-237` — existing TestAdtvFilter
- `tests/integration/test_backtest_pipeline.py` — integration smoke test

---

## Completion Notes

- **Date completed:** 2026-04-28
- **Final metrics (vs Phase 3.7):** Pending notebook re-run with full data
- **Issues encountered:**
  1. `test_fast_exit_disabled_via_huge_window_matches_phase37` — stock price array was `n_total - 2` with 2 tail values, but rebalance dates covered 3 bars; the price gain fell outside the rebalance window. Fixed by extending to `n_total - 3` with 3 tail values.
  2. `test_fast_exit_engages_when_set_below_ema100_in_bull` — initial price pattern (230 rise + 70 dip) had EMA200 above price, putting regime in BEAR instead of BULL. Fixed with (300 flat + 60 rise + 40 dip) pattern that keeps price above EMA200 but below EMA100.
- **Test count delta:** 54 tests pass (+7 new: 3 TestFastExitOverlay, 2 TestPhase38Defaults, 2 pipeline volume matrix)
- **Commit SHA:** Pending
