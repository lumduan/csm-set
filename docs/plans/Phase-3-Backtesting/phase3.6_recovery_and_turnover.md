# Phase 3.6 — Recovery Time & Turnover Fix: Dynamic Bear Mode, Relative Strength Filter, Buffer Tuning

**Feature:** Backtesting Strategy — Fix Max Recovery > 18 months, Reduce Turnover to 150–180%, Correct index_prices Bug
**Branch:** `feature/phase-3-backtesting`
**Created:** 2026-04-28
**Status:** In progress
**Depends On:** Phase 3.5 Complete

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

Phase 3.5 passed 6 of 8 exit criteria but **failed on two**:

| Criterion | Phase 3.5 Result | Target |
|---|---|---|
| Max Recovery < 18 months | **37.0 months** (FAIL) | < 18 months |
| Annualised Turnover 150–180% | **202%** (FAIL) | 150–180% |

Additionally, a **critical bug** was identified: the main backtest in Section 2 called
`MomentumBacktest.run()` without passing `index_prices`, causing the EMA-200 Market Timing
Filter to be silently skipped (Mode A / Always Bull). This means all Section 3–17 analysis
in the notebook reflects an "Always Bull" strategy, not the Hybrid engine tested in
Sections 19–22.

Phase 3.6 addresses all three issues:

1. **Max Recovery (FAIL)** — Dynamic Safe Mode: 0% equity (100% cash) when SET < EMA-200
   AND the EMA-200 slope is negative. This stops the bleeding entirely during confirmed
   downtrends, compared to 3.5's 20% equity in all Bear periods.
2. **Turnover (FAIL)** — Increase `buffer_rank_threshold` from 0.125 → 0.15 to dampen
   rotation, and add a Relative Strength filter that prevents buying underperformers vs
   the SET index (reducing churn into weak names that quickly exit).
3. **index_prices Bug** — Patch Section 2 to pass `index_prices` so the main
   `backtest_result` reflects the Hybrid engine.

### Parent Plan Reference

- `docs/plans/phase-3-backtesting/PLAN.md`

### Key Deliverables

| # | Deliverable | File(s) |
|---|---|---|
| 1 | 2 new constants: `EMA_SLOPE_LOOKBACK_DAYS`, updated `BUFFER_RANK_THRESHOLD` | `src/csm/config/constants.py` |
| 2 | `RegimeDetector.has_negative_ema_slope()` — detects falling EMA-200 | `src/csm/risk/regime.py` |
| 3 | `BacktestConfig` new fields: `bear_full_cash`, `ema_slope_lookback_days`, `relative_strength_filter`, `rs_lookback_months` | `src/csm/research/backtest.py` |
| 4 | `MomentumBacktest._has_negative_ema_slope()` — delegates to `RegimeDetector` | `src/csm/research/backtest.py` |
| 5 | `MomentumBacktest._apply_relative_strength_filter()` — remove stocks below SET index 12M return | `src/csm/research/backtest.py` |
| 6 | Updated `MomentumBacktest.run()` — dynamic Bear equity fraction, RS filter wired in | `src/csm/research/backtest.py` |
| 7 | Unit tests for all new methods (≥ 90% coverage) | `tests/unit/research/test_backtest.py`, `tests/unit/risk/test_regime.py` |
| 8 | Notebook fix: Section 2 passes `index_prices`; new Sections 23–26 | `notebooks/03_backtest_analysis.ipynb` |
| 9 | PLAN.md + this file updated | `docs/plans/phase-3-backtesting/PLAN.md` |

---

## AI Prompt

The following prompt was used to generate this phase:

```
🎯 Objective
Plan and implement Phase 3.6 of the backtesting workflow for the SET Cross-Sectional Momentum
strategy, focusing on addressing the key failure points from Phase 3.5 (notably Max Recovery > 18
months and excessive turnover), and document the plan and progress according to project standards.

📋 Context
- The project is a production-grade, type-safe, async-first Python library for backtesting and
  analyzing momentum strategies on the SET.
- Phase 3.5 introduced robust liquidity, buffer, and regime filters, but failed the Max Recovery
  < 18 months criterion (37 months observed) and had higher-than-target turnover (202% vs 150-180%).
- The codebase uses strict architectural, documentation, and testing standards (see
  `.github/instructions/`).
- All planning and implementation steps must be documented in `docs/plans/phase-3-backtesting/`.

🔧 Requirements
- Analyze and address the following:
  1. Max Recovery > 18 months: Experiment with stricter safe mode (e.g., 100% cash in Bear,
     dynamic allocation, or additional trend filters).
  2. Turnover > 180%: Test higher buffer thresholds (e.g., 0.15, 0.20) and/or reduced rebalance
     frequency (e.g., quarterly).
  3. Ensure index_prices are always provided to the backtest engine for correct EMA regime logic.
  4. Add relative strength/alpha filter to avoid buying weak stocks in Bear mode.

User Review of Phase 3.5:
1. EMA-200 Market Timing: Reduces Max DD from -50.28% to -34.98% (good). However, CAGR drops
   slightly — acceptable "cost" for 80% cash in Bear.
2. Portfolio Size 80-100 + Buffer: CAGR drops from 12.45% to 10.87% (normal for wider portfolio).
   Turnover at 202% exceeds 150-180% target.
3. FAIL — Max Recovery: 37 months (target < 18). In Bear mode with 20% equity, remaining equity
   continues bleeding. Recommend 0% equity when EMA slope is negative.
4. Recommendations:
   A. Dynamic Safe Mode: 0% equity if SET < EMA 200 AND EMA-200 slope is negative.
   B. Relative Strength Filter: Only hold stocks with positive alpha vs SET.
   C. Buffer threshold: Increase from 0.125 to 0.15.
   D. Fix index_prices bug in Section 2.
```

---

## Scope

### In Scope (Phase 3.6)

| Component | Description | Status |
|---|---|---|
| `EMA_SLOPE_LOOKBACK_DAYS` constant | 21 trading days (~1 month) for slope check | Pending |
| Updated `BUFFER_RANK_THRESHOLD` | 0.125 → 0.15 | Pending |
| `RegimeDetector.has_negative_ema_slope()` | True when EMA-200 at `asof` < EMA-200 one month ago | Pending |
| `BacktestConfig.bear_full_cash` | Bool — use 0% equity when strongly bearish | Pending |
| `BacktestConfig.ema_slope_lookback_days` | Days to look back for EMA slope (default 21) | Pending |
| `BacktestConfig.relative_strength_filter` | Bool — only hold positive-alpha stocks vs index | Pending |
| `BacktestConfig.rs_lookback_months` | Lookback for RS filter (default 12) | Pending |
| `MomentumBacktest._has_negative_ema_slope()` | Wrapper delegating to `RegimeDetector` | Pending |
| `MomentumBacktest._apply_relative_strength_filter()` | Remove stocks with 12M return < index 12M return | Pending |
| Updated `MomentumBacktest.run()` | Dynamic bear equity: 0% or 20% based on EMA slope | Pending |
| Notebook Section 2 fix | Pass `index_prices` to main backtest run | Pending |
| Notebook Sections 23–26 | Dynamic Bear, RS Filter, Buffer Sensitivity, Phase 3.6 Sign-off | Pending |
| Unit tests — regime | `has_negative_ema_slope` with rising/falling/flat EMA | Pending |
| Unit tests — backtest | RS filter, dynamic bear mode 0%/20%, full pipeline test | Pending |
| PLAN.md update | Phase 3.6 status block | Pending |

### Out of Scope (Phase 3.6)

- Quarterly rebalancing (monthly → quarterly frequency change) — try buffer fix first
- Short leg (Phase 6+)
- Bootstrap confidence intervals — Phase 4 enhancement
- API endpoints (Phase 5)
- Live data refresh (Phase 5)

---

## Design Decisions

### 1. Dynamic Safe Mode: 0% vs 20% equity based on EMA slope

Phase 3.5 uses a fixed 20% equity in ALL Bear periods. This was insufficient: during
2017–2020, the market trended down for over two years, and 20% equity continued bleeding.

Phase 3.6 introduces a two-tier Bear response:

| Condition | Equity Fraction | Cash |
|---|---|---|
| `SET > EMA-200` (Bull) | 100% | 0% |
| `SET < EMA-200` AND EMA slope is rising/flat | `safe_mode_max_equity` (20%) | 80% |
| `SET < EMA-200` AND EMA slope is negative | 0% (full cash) | 100% |

**EMA slope detection**: Compare `EMA[-1]` (today) vs `EMA[-ema_slope_lookback_days]`
(~21 days ago). If EMA is falling → confirmed downtrend → 100% cash.

This is controlled by `BacktestConfig.bear_full_cash: bool = True`. When False, reverts
to Phase 3.5 behaviour (always 20% in Bear).

### 2. Relative Strength Filter: stock must outperform SET on 12-month return

In Bull mode, momentum picks can include stocks that rank highly cross-sectionally but
still have negative absolute alpha vs the market. The RS filter removes them before the
buffer selection step:

```
rs_alpha = stock_12m_return - index_12m_return
keep if rs_alpha > 0
```

This runs only when `index_prices` is provided and `relative_strength_filter=True`.
Stocks with insufficient price history (< 12M) are excluded conservatively.

The RS filter serves two purposes:
- **Quality gate**: avoids "weak bulls" that are rising slowly but underperforming SET
- **Churn reduction**: stocks that fail the RS test exit sooner, reducing buffer pressure

### 3. Buffer threshold: 0.125 → 0.15

The 12.5 percentile gap was chosen as a midpoint between 10–15% in Phase 3.5. The observed
202% turnover exceeded the 150–180% target. Raising to 0.15 (15 percentile points) will:
- Require a replacement to rank 15+ percentile points higher before evicting a holding
- Estimated impact: reduce turnover by 15–25% (from 202% to ~160–175%)

`BUFFER_RANK_THRESHOLD` in `constants.py` is updated from 0.125 to 0.15.

### 4. index_prices must be passed in Section 2

The main `backtest_result` object (used in Sections 3–17) must reflect the Hybrid engine.
This requires passing the `benchmark_series` (with correct timezone) as `index_prices`.
Without this, the EMA trend filter is silently bypassed and Safe Mode is never triggered,
making the displayed results misleading.

### 5. RS filter applies in Bull Mode only

In Bear Mode (especially with 0% equity), the RS filter is moot — the portfolio holds cash.
The filter is applied only when `cross_section` is non-empty and mode is `BULL` or weak
`BEAR` (i.e., before the equity fraction is computed). This avoids unnecessary computation
and edge cases when index_prices data near the asof date is sparse.

---

## Implementation Steps

### Step 1: Update `constants.py`

Add:
```python
EMA_SLOPE_LOOKBACK_DAYS: int = 21   # trading days to detect falling EMA-200
```
Update:
```python
BUFFER_RANK_THRESHOLD: float = 0.15  # raised from 0.125 to reduce turnover
```

Add `EMA_SLOPE_LOOKBACK_DAYS` to `__all__`.

### Step 2: Add `has_negative_ema_slope()` to `RegimeDetector`

```python
def has_negative_ema_slope(
    self,
    index_prices: pd.Series,
    asof: pd.Timestamp,
    window: int = 200,
    slope_lookback: int = 21,
) -> bool:
    """Return True when EMA-window is falling at asof.

    Compares EMA at asof vs EMA at asof minus slope_lookback bars.
    Returns False when there is insufficient history (conservative —
    does not trigger 100% cash prematurely).
    """
    history = index_prices.loc[index_prices.index <= asof].dropna()
    ema = self.compute_ema(history, window)
    if len(ema) < slope_lookback + 1:
        return False   # not enough data to measure slope
    return bool(float(ema.iloc[-1]) < float(ema.iloc[-(slope_lookback + 1)]))
```

### Step 3: Extend `BacktestConfig`

Add four fields:
```python
bear_full_cash: bool = Field(default=True)
ema_slope_lookback_days: int = Field(default=EMA_SLOPE_LOOKBACK_DAYS)
relative_strength_filter: bool = Field(default=True)
rs_lookback_months: int = Field(default=12)
```

Update default:
```python
buffer_rank_threshold: float = Field(default=BUFFER_RANK_THRESHOLD)  # now 0.15
```

### Step 4: Add `_has_negative_ema_slope()` to `MomentumBacktest`

```python
def _has_negative_ema_slope(
    self,
    index_prices: pd.Series,
    asof: pd.Timestamp,
    ema_window: int,
    slope_lookback: int,
) -> bool:
    return self._regime.has_negative_ema_slope(
        index_prices, asof, window=ema_window, slope_lookback=slope_lookback
    )
```

### Step 5: Add `_apply_relative_strength_filter()` to `MomentumBacktest`

```python
def _apply_relative_strength_filter(
    self,
    cross_section: pd.DataFrame,
    prices: pd.DataFrame,
    index_prices: pd.Series,
    asof: pd.Timestamp,
    lookback_months: int = 12,
) -> pd.DataFrame:
    """Remove stocks with 12-month return below the SET index 12-month return."""
    lookback_days = lookback_months * 21  # approximate trading days
    idx_hist = index_prices.loc[index_prices.index <= asof].dropna().tail(lookback_days)
    if len(idx_hist) < 2:
        return cross_section  # insufficient benchmark history — skip filter
    index_return = float(idx_hist.iloc[-1] / idx_hist.iloc[0] - 1.0)
    keep = []
    for sym in cross_section.index:
        if sym not in prices.columns:
            continue
        hist = prices[sym].loc[:asof].dropna().tail(lookback_days)
        if len(hist) < 2:
            continue  # conservatively exclude
        stock_return = float(hist.iloc[-1] / hist.iloc[0] - 1.0)
        if stock_return >= index_return:
            keep.append(sym)
    excluded = len(cross_section) - len(keep)
    if excluded:
        logger.debug("RS filter excluded %d symbols at %s", excluded, asof)
    return cross_section.loc[keep]
```

### Step 6: Update `MomentumBacktest.run()` loop

In the rebalance loop, after ADTV filter and mode computation:

```python
# Apply Relative Strength filter (Bull mode, index_prices available)
if config.relative_strength_filter and index_prices is not None:
    cross_section = self._apply_relative_strength_filter(
        cross_section, prices, index_prices, current_date, config.rs_lookback_months
    )
if cross_section.empty:
    continue

# Dynamic Bear equity fraction
if mode is RegimeState.BEAR:
    if config.bear_full_cash and index_prices is not None:
        strong_bear = self._has_negative_ema_slope(
            index_prices, current_date,
            config.ema_trend_window, config.ema_slope_lookback_days
        )
        equity_fraction = 0.0 if strong_bear else config.safe_mode_max_equity
    else:
        equity_fraction = config.safe_mode_max_equity
else:
    equity_fraction = 1.0

# After computing target_weights:
if equity_fraction < 1.0:
    target_weights = target_weights * equity_fraction
```

### Step 7: Write unit tests

**`tests/unit/risk/test_regime.py`** — extend:
- `test_has_negative_ema_slope_when_ema_falling` — declining price series → True
- `test_has_negative_ema_slope_when_ema_rising` — rising price series → False
- `test_has_negative_ema_slope_insufficient_history` — < window+slope_lookback bars → False

**`tests/unit/research/test_backtest.py`** — extend:
- `test_rs_filter_excludes_underperformers` — stock below index 12M return is excluded
- `test_rs_filter_passes_outperformers` — stock above index 12M return is kept
- `test_rs_filter_insufficient_benchmark_history_skips` — too few index bars → no filter
- `test_run_strong_bear_uses_zero_equity` — when EMA slope negative → NAV flat (cash)
- `test_run_weak_bear_uses_safe_mode_equity` — EMA slope flat → 20% equity applied
- `test_run_bear_full_cash_false_uses_safe_mode` — bear_full_cash=False → 20% always

### Step 8: Patch notebook Section 2 and add Sections 23–26

**Section 2 fix** — pass `index_prices`:
```python
# Build index_prices series with timezone consistent with prices_wide
_index_prices_bt: pd.Series | None = None
if benchmark_series is not None:
    _index_prices_bt = benchmark_series.copy()
    if _index_prices_bt.index.tz is None:
        _index_prices_bt.index = _index_prices_bt.index.tz_localize('Asia/Bangkok')
    elif str(_index_prices_bt.index.tz) != 'Asia/Bangkok':
        _index_prices_bt.index = _index_prices_bt.index.tz_convert('Asia/Bangkok')

backtest_result = backtest.run(
    feature_panel, prices_wide, config,
    volumes=volumes_wide if not volumes_wide.empty else None,
    index_prices=_index_prices_bt,
)
```

**Section 23: Dynamic Safe Mode** (Thai markdown)
- Compare equity curves: Phase 3.5 (20% equity always in Bear) vs Phase 3.6 (0% equity when EMA slope negative)
- Recovery period table for both — confirm 3.6 < 18 months

**Section 24: Relative Strength Filter** (Thai markdown)
- Universe size before/after RS filter at each rebalance date (line chart)
- Compare CAGR, Sharpe, Max DD, Turnover with/without RS filter
- Verify RS filter reduces turnover

**Section 25: Buffer Threshold Sensitivity** (Thai markdown)
- Run backtest at buffer=0.125, 0.15, 0.20 — table: Turnover, CAGR, Sharpe for each
- Confirm 0.15 achieves target turnover without significant CAGR sacrifice

**Section 26: Phase 3.6 Final Stress Test + Sign-off** (Thai markdown)
- Cost sensitivity at 15/20/25 bps with full Phase 3.6 config (RS filter + dynamic bear + buffer 0.15)
- Check Max Recovery < 18 months at each cost level
- PASS/FAIL sign-off for all Phase 3.6 exit criteria

---

## File Changes

| File | Action | Description |
|---|---|---|
| `src/csm/config/constants.py` | MODIFY | Add `EMA_SLOPE_LOOKBACK_DAYS`; update `BUFFER_RANK_THRESHOLD` 0.125 → 0.15 |
| `src/csm/risk/regime.py` | MODIFY | Add `has_negative_ema_slope()` method |
| `src/csm/research/backtest.py` | MODIFY | 4 new `BacktestConfig` fields; `_has_negative_ema_slope`, `_apply_relative_strength_filter`; updated `run()` |
| `tests/unit/risk/test_regime.py` | MODIFY | Add 3 tests for `has_negative_ema_slope` |
| `tests/unit/research/test_backtest.py` | MODIFY | Add 6 tests for RS filter and dynamic Bear mode |
| `notebooks/03_backtest_analysis.ipynb` | MODIFY | Fix Section 2; add Sections 23–26 |
| `docs/plans/phase-3-backtesting/PLAN.md` | MODIFY | Add Phase 3.6 status block |
| `docs/plans/phase-3-backtesting/phase3.6_recovery_and_turnover.md` | CREATE | This plan document |

---

## Success Criteria

- [ ] `uv run pytest tests/ -v -m "not integration"` exits 0
- [ ] `uv run mypy src/` exits 0
- [ ] `uv run ruff check src/ scripts/` exits 0
- [ ] `RegimeDetector.has_negative_ema_slope()` returns True for falling EMA, False for rising
- [ ] Dynamic Bear Mode uses 0% equity when EMA-200 slope is negative
- [ ] Dynamic Bear Mode uses 20% equity when below EMA but slope is flat/rising
- [ ] RS filter removes stocks with 12M return below SET index
- [ ] Annualised Turnover < 180% with buffer=0.15 + RS filter (verified in Section 25)
- [ ] Max Recovery < 18 months at 20 bps (verified in Section 26)
- [ ] Section 2 backtest runs with `index_prices` — no "EMA filter skipped" warning
- [ ] All 4 new notebook sections (23–26) execute error-free with Thai markdown
- [ ] Phase 3.6 sign-off cell in Section 26 prints PASS for all criteria

---

## Completion Notes

### Summary

Phase 3.6 implemented 2026-04-28. All code delivered; notebook Sections 23–26 executed
error-free. However, two of four success criteria remain FAIL — see findings below.

**What was delivered:**
1. `RegimeDetector.has_negative_ema_slope()` — detects falling EMA-200 slope
2. `BacktestConfig` 4 new fields: `bear_full_cash`, `ema_slope_lookback_days`,
   `relative_strength_filter`, `rs_lookback_months`
3. `MomentumBacktest._has_negative_ema_slope()` and `_apply_relative_strength_filter()`
4. Dynamic Bear equity: 0% when EMA slope negative, 20% when slope flat/rising
5. `BUFFER_RANK_THRESHOLD` updated 0.125 → 0.15; `EMA_SLOPE_LOOKBACK_DAYS = 21` added
6. **Critical bug fixed**: Section 2 now passes `index_prices` → EMA filter correctly applied
7. Sections 23–26 added to notebook (all execute error-free, all Thai markdown)
8. 9 new unit tests added (36 total for regime + backtest, all pass)

### Research Findings (Phase 3.6 results vs targets)

| Criterion | Target | Phase 3.5 | Phase 3.6 | Status |
|---|---|---|---|---|
| Max Recovery | < 18M | 37.0M | 44.0M | ❌ WORSE |
| Annualised Turnover | 150–180% | 202% | 220% | ❌ WORSE |
| Sharpe @20bps | > 0.5 | 0.543 | 0.499 | ❌ FAIL |
| CAGR (adj.) > Benchmark | ✓ | ✅ | ✅ | ✅ PASS |
| index_prices bug | Fixed | Bug | Fixed | ✅ PASS |

### Root Cause Analysis

**Why Dynamic Bear (0% equity) made recovery time WORSE (37M → 44M):**

The 0% equity allocation correctly avoids crash losses but also delays recovery
participation. EMA-200 slope takes months to turn positive after a crash. During the
entire 2020 recovery rally (Apr–Dec 2020), the EMA slope was still negative — so the
portfolio stayed at 0% equity and missed all of the recovery gains. The portfolio's
NAV peak before the episode was set at a pre-crash high; by being in cash and missing
the early recovery, it took longer to reach that peak again.

**Why RS Filter increased turnover (202% → 220%):**

The RS filter removes stocks from `cross_section` BEFORE buffer logic runs. When a
holding is removed by RS filter, buffer logic cannot protect it. The next month it may
pass RS again and be re-admitted — creating a churn cycle. The buffer threshold (0.125
or 0.15 or 0.20) had zero effect on turnover when RS filter was active because the RS
gate bypassed it entirely (confirmed: turnover identical at all three buffer levels).

### Issues Encountered

1. **Dynamic Bear (0% equity) actually delayed recovery** — Trend-following strategies
   on SET suffer from "late re-entry" after crashes. EMA-200 slope can stay negative
   for 6–12 months into the recovery, causing the portfolio to miss early rally gains.
   This increased the worst episode from 37M to 44M.

2. **RS Filter interaction with buffer** — RS filter applied before buffer means it can
   evict existing holdings without buffer protection. This breaks the turnover-reduction
   intent of the buffer. Fix requires either: (a) applying RS filter only to candidates
   (not existing holdings), or (b) disabling RS filter by default.

3. **SET market structural challenge** — The 2017–2021 episode (38.8M in base data) is
   driven by a prolonged Thai market downturn + COVID crash. No simple momentum + regime
   filter can reduce this episode to < 18M without fundamentally changing the strategy.

### Recommended Next Steps (Phase 3.7)

1. **Fix RS filter to respect buffer**: Apply RS filter only to NEW candidates (not
   current holdings). This preserves buffer protection for existing holdings, reducing
   churn caused by RS gate.
2. **Re-entry signal for recovery**: Instead of waiting for EMA slope to turn positive,
   add a re-entry trigger (e.g., price > 50-day EMA or 3-month momentum positive) to
   re-enter equity faster after crashes.
3. **Accept the recovery constraint**: The 18-month target may be unachievable on SET
   given the 2015–2017 and 2017–2021 episodes. Consider relaxing to 24M or focusing
   on other risk metrics (Max DD, Calmar ratio) instead.

---

**Document Version:** 1.1
**Author:** AI Agent (Claude Sonnet 4.6)
**Status:** Complete (research findings documented; targets partially unmet)
**Created:** 2026-04-28
**Completed:** 2026-04-28
