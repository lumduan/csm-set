# Phase 4 — Portfolio Construction & Risk Management Master Plan

**Feature:** Production-grade Portfolio Construction & Risk Management Layer for the SET Cross-Sectional Momentum Strategy
**Branch:** `feature/phase-4-portfolio-construction`
**Created:** 2026-04-29
**Status:** Draft — awaiting implementation
**Depends on:** Phase 1 (Data Pipeline — complete), Phase 2 (Signal Research — complete), Phase 3 (Backtesting — complete through 3.9)
**Positioning:** Production layer — promotes the validated Phase 3.9 inline logic into composable, testable, live-trading-ready modules and adds the volatility scaling, liquidity/capacity, and drawdown circuit-breaker overlays that the strategy needs before it can be wired into the API/UI/scheduler in Phases 5–6.

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

Phase 4 takes the validated Phase 3.9 backtest configuration — which today lives as a tangle of inline helpers inside `MomentumBacktest.run()` — and turns it into a **production-grade portfolio construction and risk management layer**. The goal is two-fold:

1. **Refactor**: extract the validated Phase 3.9 logic (selection / sector cap / vol scaling / regime gating) into clean, composable, individually testable modules under `csm.portfolio.*` and `csm.risk.*` without changing strategy semantics.
2. **Extend**: add the three risk overlays that Phase 3.9 explicitly flagged as Phase 4 follow-ups — a portfolio-level **volatility scaling engine**, a **liquidity/capacity overlay**, and a **drawdown circuit breaker** — and an **execution simulator** that produces deterministic trade lists with realistic slippage. The result is a backtest stack that is byte-for-byte equivalent to Phase 3.9 when the new overlays are disabled, and that is ready to drive a live-trading API / scheduler in Phase 5.

### Scope

Phase 4 covers eight sub-phases in dependency order:

| Sub-phase | Deliverable | Purpose |
|---|---|---|
| 4.1 | Portfolio Construction Layer | First-class `PortfolioConstructor` API replacing inline `_select_holdings()` |
| 4.2 | Weight Optimizer Expansion | `equal_weight`, `vol_target`, `inverse_vol`, `min_variance` with shared constraint engine |
| 4.3 | Volatility Scaling Engine | Extract `_apply_vol_scaling()` into `VolScalingOverlay`; portfolio-vol target as overlay; lock `vol_scaling_enabled=True` as default |
| 4.4 | Liquidity & Capacity Overlay | ADV participation cap, per-position notional cap, strategy capacity curve |
| 4.5 | Drawdown Circuit Breaker | Rolling DD trigger → safe-mode equity fraction → recovery condition |
| 4.6 | Sector & Regime Constraint Engine | Extract `_apply_sector_cap()`; integrate `RegimeDetector` as portfolio-level overlay |
| 4.7 | Execution Simulation & Trade List | Slippage model, capacity-aware sizing, `TradeList` output |
| 4.8 | Portfolio Optimization Notebook & Walk-Forward Gate | `notebooks/04_portfolio_optimization.ipynb` + walk-forward CI gate spec |

**Out of scope for Phase 4:**

- Live broker connectors (SETTRADE, paper broker) — deferred to a post-Phase 5 enhancement
- VaR / CVaR position limits — deferred to Phase 9 enhancement
- Multi-strategy / multi-portfolio aggregation — deferred to Phase 9
- API / UI / scheduler integration — that's Phase 5 and 6
- Live data refresh / order routing — Phase 5

### Validated Inputs from Phase 3.9

Phase 4 builds on the **validated, stability-first Phase 3.9 configuration**. These are non-negotiable inputs that Phase 4 must preserve:

| Parameter | Phase 3.9 Validated Value | Notes |
|---|---|---|
| `rebalance_every_n` | `1` (monthly) | Validated against {1, 2, 3} sweep |
| `vol_scaling_enabled` | `True` (Phase 4 default change) | Phase 3.9 demonstrated stability with vol scaling on |
| `vol_target_annual` | `0.15` (15%) | Portfolio realised-vol target |
| `vol_lookback_days` | `63` | ~3 months trailing |
| `vol_scale_cap` | `1.5` | Multiplier ceiling (no leverage above 1.5×) |
| `sector_max_weight` | `0.35` | Hard cap per sector |
| `exit_rank_floor` | `0.35` | Unconditional eviction below 35th percentile |
| `buffer_rank_threshold` | `0.25` | Replacement buffer band |
| `n_holdings_min / max` | `40 / 60` | Concentration band |
| `adtv_63d_min_thb` | `5_000_000` | Backtest liquidity gate |
| `transaction_cost_bps` | `15.0` | Per side |
| `ema_trend_window / fast_reentry_ema_window / exit_ema_window` | `200 / 50 / 100` | Regime EMAs |
| `safe_mode_max_equity` | `0.20` | BEAR / EMA100-fast-exit equity cap |
| `bear_full_cash` | `True` | EMA200 negative-slope → full cash |
| `rs_filter_mode` | `"entry_only"` | RS gates new entries only |
| Walk-forward | 5-fold expanding-window, 1y test, 5y min train | OOS Sharpe > 0 across all folds |

Phase 3.9 reported (Phase 3.8 baseline): CAGR 12.52%, Sharpe 0.663, Max DD −31.03%, Win Rate 43.9%. Phase 4's new overlays must not regress CAGR by more than 1pp, must improve Max DD by ≥ 5pp, and must keep all 5 walk-forward OOS Sharpes positive.

---

## Problem Statement

The Phase 3.9 backtest validates the strategy's edge, but the implementation is monolithic: every overlay (vol scaling, sector cap, regime gating, ADTV filter) lives as a private method on `MomentumBacktest`. Three problems must be solved before this strategy can drive a production system:

1. **Composability** — to reason about each overlay independently (and turn them on/off in stress tests), they must be standalone modules with a uniform `apply(state) -> state` contract.
2. **Live-trading readiness** — the backtest produces an equity curve, not a trade list. Live trading requires deterministic per-rebalance trade lists with target weights, share counts, slippage estimates, and capacity checks.
3. **Risk overlays the backtest doesn't yet have** —
   - **Capacity:** Phase 3.9 has an ADTV gate but no per-position sizing constraint (no participation rate cap). At AUM > ~100M THB, naive equal-weighting on ~50 names will hit thinly traded SET symbols hard.
   - **Drawdown circuit breaker:** Phase 3.9 has regime overlays (EMA200/EMA100), but no symmetric, rule-based de-risking trigger keyed off realised portfolio drawdown. The strategy can still bleed −31% in adverse regimes.
   - **Vol scaling as a first-class overlay:** Phase 3.9 ships `_apply_vol_scaling()` but disables it by default. With it on, Phase 3.9's parameter sweep showed materially better risk-adjusted profile — Phase 4 makes that the default.

Solving these three problems is the prerequisite for Phases 5 (API) and 6 (UI).

---

## Design Rationale

### Composable Overlay Pattern

Every Phase 4 overlay implements the same minimal protocol:

```python
class PortfolioOverlay(Protocol):
    def apply(self, state: PortfolioState, ctx: OverlayContext) -> PortfolioState: ...
```

Where `PortfolioState` is a Pydantic model carrying current target weights, equity fraction, regime, rebalance date, and a journal of overlay decisions. Each overlay reads, mutates, and returns the state. This makes the rebalance pipeline a pure composition:

```
select → optimize → sector_cap → regime_gate → vol_scale → capacity → circuit_breaker → trade_list
```

The order is deterministic and documented. Stress tests selectively disable overlays by replacing them with `IdentityOverlay()`. There is exactly one place where the order changes (`PortfolioPipeline.compose()`); a single change has zero blast radius.

### Refactor First, Extend Second

The 8 sub-phases are intentionally split: 4.1–4.2 and 4.6 are pure refactors of validated Phase 3.9 logic; 4.3–4.5 and 4.7 are new overlays. The refactor sub-phases must produce **identical backtest output** to Phase 3.9 (verified by a snapshot test on the equity curve to 1e-9 tolerance). Only after that snapshot test passes does the new-overlay work begin. This isolates strategy-correctness risk from new-feature risk.

### vol_scaling=True as the New Default

Phase 3.9 left vol scaling off by default to preserve backwards compatibility with Phase 3.8 results. Phase 4 inverts this: `BacktestConfig.vol_scaling_enabled=True` is the production default. The user opted into this change (2026-04-29) on the basis that Phase 3.9's sweep demonstrated lower drawdown without material CAGR loss. The Phase 3.8 baseline remains reproducible by setting the flag to `False`.

### Trade List, Not Order Router

"Live-trading-ready" in Phase 4 means the strategy produces a fully-specified `TradeList[Trade]` at every rebalance: target weight, current weight, delta weight, target shares, side (buy/sell/hold), notional, expected slippage, and a `capacity_violation` flag. It does **not** mean broker connectors. A future phase will plug `TradeList` into a broker adapter; Phase 4 keeps that interface clean by treating execution as a pure function of the rebalance state.

### Slippage Model: Square-Root Impact + Half-Spread

The execution simulator uses the industry-standard square-root market-impact model (Almgren–Chriss-inspired) with a half-spread component:

```
slippage_bps = half_spread_bps + impact_coef × sqrt(participation_rate)
```

Defaults (`impact_coef=10`, `half_spread_bps=10`) are calibrated to be conservative for SET mid/large-caps. Real calibration is a Phase 9 enhancement; Phase 4 ships the model with the parameters exposed in `ExecutionConfig`.

### Drawdown Circuit Breaker: Rolling, Not Peak-to-Trough

The breaker uses **rolling N-day drawdown** (default 60 trading days) rather than peak-to-trough max DD. Rationale: peak-to-trough max DD is monotonic — once breached, it remains breached forever, which would lock the strategy into safe-mode permanently. Rolling DD recovers as the window rolls past the trough, giving a natural recovery condition.

### Capacity Overlay: ADV-% Hard Cap

Each target position is checked against a configurable percentage of average daily volume (default 10% ADV). Positions exceeding the cap are size-reduced (not dropped — dropping breaks the holdings count band). The reduced notional is held as cash; the strategy's effective equity fraction declines proportionally and is recorded in the state journal for stress-test analysis.

### DataFrame Boundary Preserved

OHLCV and feature panels remain pandas DataFrames per the project-wide approved exception. All overlay configs, state objects, trade lists, and overlay contexts are Pydantic models. Boundaries between overlays are typed and validated.

---

## Architecture

### Directory Layout

```
src/csm/
├── portfolio/
│   ├── construction.py            # PortfolioConstructor — quintile selection + buffer + exit floor
│   ├── optimizer.py               # WeightOptimizer — equal / vol_target / inverse_vol / min_variance
│   ├── constraints.py             # NEW — sector cap, position size cap, holdings count band
│   ├── pipeline.py                # NEW — PortfolioPipeline.compose() — overlay orchestrator
│   ├── rebalance.py               # RebalanceScheduler — unchanged from existing
│   ├── state.py                   # NEW — PortfolioState, OverlayContext, OverlayJournalEntry
│   └── exceptions.py              # PortfolioError, OptimizationError, ConstraintViolationError
├── risk/
│   ├── vol_scaling.py             # NEW — VolScalingOverlay (extracted from backtest.py)
│   ├── capacity.py                # NEW — CapacityOverlay (ADV%, position notional, strategy capacity)
│   ├── circuit_breaker.py         # NEW — DrawdownCircuitBreaker (rolling DD, safe-mode, recovery)
│   ├── regime.py                  # Existing — extended to expose RegimeOverlay wrapper
│   ├── metrics.py                 # Existing — unchanged
│   ├── drawdown.py                # Existing — extended with rolling_drawdown(window)
│   └── exceptions.py              # RiskError, CircuitBreakerTripped
├── execution/
│   ├── __init__.py                # NEW package
│   ├── simulator.py               # NEW — ExecutionSimulator (slippage, trade list)
│   ├── slippage.py                # NEW — SqrtImpactSlippageModel
│   └── trade_list.py              # NEW — TradeList, Trade, ExecutionResult
└── research/
    ├── backtest.py                # REFACTORED — uses PortfolioPipeline; semantics unchanged when overlays match Phase 3.9
    └── walk_forward.py            # Existing — Phase 4 adds CI gate spec doc

notebooks/
└── 04_portfolio_optimization.ipynb  # NEW — comparison + stress test + final config decision

tests/unit/
├── portfolio/
│   ├── test_construction.py       # Existing — extended
│   ├── test_optimizer.py          # Existing — extended for new schemes
│   ├── test_constraints.py        # NEW
│   ├── test_pipeline.py           # NEW — overlay composition tests
│   └── test_state.py              # NEW
├── risk/
│   ├── test_vol_scaling.py        # NEW
│   ├── test_capacity.py           # NEW
│   ├── test_circuit_breaker.py    # NEW
│   ├── test_regime.py             # Existing — extended
│   └── test_drawdown.py           # Existing — extended
├── execution/
│   ├── test_simulator.py          # NEW
│   ├── test_slippage.py           # NEW
│   └── test_trade_list.py         # NEW
└── research/
    └── test_backtest_phase4_parity.py  # NEW — snapshot test: Phase 3.9 config produces byte-identical equity curve
```

### Dependency Graph

```
PortfolioState, OverlayContext        (no deps — pure Pydantic)
    ↑
PortfolioConstructor    WeightOptimizer    Constraints    RegimeDetector   DrawdownAnalyzer
    ↑                       ↑                  ↑                ↑               ↑
    └───────── PortfolioPipeline (composes overlays in fixed order) ──────────┘
                            ↑
                    ExecutionSimulator (consumes final state → TradeList)
                            ↑
                    MomentumBacktest.run() (drives the pipeline at every rebalance)
                            ↑
                    WalkForwardAnalyzer (runs MomentumBacktest per fold)
```

### Rebalance Pipeline (per rebalance date)

```
[1] Universe snapshot for date          (ParquetStore — Phase 1)
        ↓
[2] Feature panel slice                 (FeaturePipeline — Phase 2)
        ↓
[3] PortfolioConstructor.select(...)    (top-quintile + buffer + exit floor)
        ↓
[4] WeightOptimizer.compute(...)        (equal / vol_target / inverse_vol / min_var)
        ↓
[5] SectorCapOverlay.apply(...)         (Phase 3.9 35% cap, extracted)
        ↓
[6] RegimeOverlay.apply(...)            (BULL/BEAR/EARLY_BULL → safe-mode equity gate)
        ↓
[7] VolScalingOverlay.apply(...)        (portfolio realised vol → equity fraction in [0, vol_scale_cap])
        ↓
[8] CapacityOverlay.apply(...)          (ADV% cap → per-position size reduction)
        ↓
[9] DrawdownCircuitBreaker.apply(...)   (rolling DD threshold → safe-mode + recovery condition)
        ↓
[10] ExecutionSimulator.simulate(...)   (delta weights → trade list with slippage)
        ↓
[11] PortfolioState (final) + TradeList → BacktestResult.append(...)
```

---

## Implementation Phases

### Phase 4.1 — Portfolio Construction Layer

**Status:** `[x]` Complete — 2026-04-29
**Goal:** Promote Phase 3.9's inline `MomentumBacktest._select_holdings()` into a first-class `PortfolioConstructor` API. No semantic change.

**Deliverables:**

- [x] `src/csm/portfolio/construction.py` — `PortfolioConstructor`
  - [x] `select(cross_section: pd.DataFrame, current_holdings: list[str], config: SelectionConfig, *, entry_mask: set[str] | None = None) -> SelectionResult`
  - [x] Implements top-quintile + replacement buffer + exit-rank floor (Phase 3.7–3.9 logic verbatim)
  - [x] Returns `SelectionResult` Pydantic model: selected symbols, evicted symbols, retained symbols, ranks
- [x] `src/csm/portfolio/state.py` — `PortfolioState`, `OverlayContext`, `OverlayJournalEntry`, `CircuitBreakerState` Pydantic models
- [x] `src/csm/portfolio/exceptions.py` — extend with `SelectionError`
- [x] Unit tests (17 cases): top-quintile selection, buffer band retains current holdings within band, exit floor evicts unconditionally, holdings count band enforced (40 ≤ n ≤ 60), entry mask restriction, small universe fallback, deterministic for fixed input
- [x] Snapshot parity test in `tests/unit/research/test_backtest_phase4_parity.py`: PortfolioConstructor parity with inline Phase 3.9, ranks match (1e-9 tolerance), injected constructor used by MomentumBacktest
- [x] `MomentumBacktest._select_holdings()` delegates to `PortfolioConstructor`; `_apply_buffer_logic()` extracted
- [x] All quality gates pass: ruff clean, mypy clean, 86/86 tests pass (zero regressions)

**Completion Notes:** Phase 4.1 implemented in a single session. `PortfolioConstructor.select()` promoted the full Phase 3.9 inline logic with no semantic change. `_apply_buffer_logic()` moved as a private static method returning `tuple[list, list, list]` for richer eviction/retention tracking. Snapshot parity confirmed via 4 dedicated tests. MomentumBacktest accepts an optional `portfolio_constructor` parameter for testability. All 51 existing backtest tests continue to pass unchanged.

---

### Phase 4.2 — Weight Optimizer Expansion

**Status:** `[x]` Complete — 2026-04-29
**Goal:** Expand the existing `WeightOptimizer` stub into a production weighting engine with `equal_weight`, `vol_target`, `inverse_vol`, `min_variance`, `max_sharpe` (Monte Carlo). Lock `vol_target` as default.

**Deliverables:**

- [x] `src/csm/portfolio/optimizer.py` — extended `WeightOptimizer`
  - [x] `compute(symbols: list[str], prices: pd.DataFrame, scheme: WeightScheme, config: OptimizerConfig) -> pd.Series`
  - [x] Schemes: `EQUAL`, `INVERSE_VOL`, `VOL_TARGET`, `MIN_VARIANCE`, `MAX_SHARPE` (StrEnum)
  - [x] All weights sum to 1.0; long-only; min position floor (1%); max position cap (10%)
  - [x] Min-variance uses `scipy.optimize.minimize` with SLSQP; falls back to inverse-vol on solver failure
  - [x] Max-Sharpe via vectorised Monte Carlo (Dirichlet, 100k samples); falls back to inverse-vol on failure
- [x] `OptimizerConfig` Pydantic model with `min_position`, `max_position`, `vol_lookback_days`, `target_position_vol`, `solver_max_iter`, `mc_samples`, `mc_risk_free_rate`
- [x] `MonteCarloResult` Pydantic model with efficient frontier data, max-Sharpe weights, and equal-weight benchmark
- [x] `monte_carlo_frontier()` standalone utility for analysis/visualisation
- [x] Unit tests (34 cases): weight sum invariant, position-cap enforcement, vol-target inverse-relationship, min-variance solver convergence, fallback paths, Monte Carlo frontier, determinism
- [x] Snapshot parity: `WeightScheme.EQUAL` reproduces Phase 3.9 equity curve to 1e-9

**Completion Notes:** All five weighting schemes implemented. Monte Carlo engine uses batch Dirichlet sampling + vectorised `np.einsum` for O(100k) performance in <1s. Position constraints enforced via iterative cap-then-floor redistribution with unsatisfiability detection. Existing methods preserved for backward compatibility with `backtest.py`. All gates pass: ruff clean, mypy strict, 34/34 tests.

---

### Phase 4.3 — Volatility Scaling Engine

**Status:** `[x]` Complete — 2026-04-29
**Goal:** Extract `MomentumBacktest._apply_vol_scaling()` into a standalone `VolatilityScaler` module. Lock `vol_scaling_enabled=True` as default.

**Deliverables:**

- [x] `src/csm/portfolio/vol_scaler.py` — `VolatilityScaler` (standalone)
  - [x] `scale(weights: pd.Series, prices: pd.DataFrame, config: VolScalingConfig) -> tuple[pd.Series, VolScalingResult]`
  - [x] Computes weighted portfolio realised vol via dot product over `lookback_days` (default 63)
  - [x] Scale factor = `clamp(target_annual / realised_vol, floor, cap)`, equity fraction = `min(scale_factor, 1.0)`
  - [x] `_compute_realized_vol()` static method for standalone use
- [x] `VolScalingConfig` Pydantic model: `enabled=True`, `target_annual=0.15`, `lookback_days=63`, `cap=1.5`, `floor=0.0`, `regime_aware=False`
- [x] `VolScalingResult` Pydantic model: `realized_vol_annual`, `scale_factor`, `equity_fraction`
- [x] `BacktestConfig.vol_scaling_enabled` default flipped from `False` → `True`
- [x] `BacktestConfig` adds `vol_scaling_config: VolScalingConfig | None = None`
- [x] Unit tests (22 cases): config validation, disabled pass-through, high/low/zero vol, insufficient history, empty weights, single asset, floor enforcement, equity cap, weight sum invariant, concentrated weights, missing symbol, all-zero weights, realized vol computation
- [x] All quality gates pass: ruff clean, mypy clean, 22/22 tests pass, 0 regressions

**Completion Notes:** Phase 4.3 implemented the standalone `VolatilityScaler` at `src/csm/portfolio/vol_scaler.py` (deviating from the original PLAN.md file path `src/csm/risk/vol_scaling.py`). The module uses weighted dot-product portfolio vol rather than equal-weight mean, improving accuracy when weights are non-uniform. The pipeline overlay adapter (consuming `PortfolioState`) is deferred to Phase 4.6.

---

### Phase 4.4 — Liquidity & Capacity Overlay

**Status:** `[x]` Complete — 2026-04-29
**Goal:** Add the per-position ADV-participation cap and strategy-capacity curve that Phase 3.9 lacks.

**Deliverables:**

- [x] `src/csm/portfolio/liquidity_overlay.py` — `LiquidityOverlay`
  - [x] `apply(weights, prices, volumes, config) -> tuple[pd.Series, LiquidityResult]`
  - [x] For each target position: max notional = `adv_cap_pct × ADV_thb` where `ADV_thb` is 63-day average daily turnover
  - [x] Position notional reduced if cap binding; excess held as cash
  - [x] Aggregate effective equity fraction adjusted; recorded in `LiquidityResult`
  - [x] `PositionLiquidityInfo` per-position: `target_notional`, `capped_notional`, `participation_rate`, `cap_binding`
- [x] `LiquidityConfig` Pydantic model: `enabled=True`, `adv_cap_pct=0.10`, `adtv_lookback_days=63`, `assumed_aum_thb=200_000_000`
- [x] **Strategy capacity curve** helper: `compute_capacity_curve(weights, prices, volumes, config, aum_grid) -> pd.DataFrame` returning aggregate participation rate, fraction of trades capped, effective equity fraction at each AUM
- [x] Unit tests (27 cases): cap binds at high AUM, no-op at low AUM, ADV computation matches manual, capacity curve monotonic in AUM, edge cases (zero volume, single-name portfolio, missing data)
- [x] Snapshot parity: `enabled=False` reproduces pass-through (equity_fraction=1.0, weights unchanged)

**Completion Notes:** Phase 4.4 implemented the standalone `LiquidityOverlay` at `src/csm/portfolio/liquidity_overlay.py` (deviating from the original PLAN.md path `src/csm/risk/capacity.py` to follow the Phase 4.3 convention). The module uses the same ADTV formula as `_apply_adtv_filter()` (mean of close × volume over 63 trailing bars) for consistency with the Phase 3.9 binary filter. Illiquid assets are zeroed rather than dropped to preserve index shape. Excess weight is held as cash rather than redistributed to avoid cascading cap effects. The pipeline overlay adapter is deferred to Phase 4.6.

---

### Phase 4.5 — Drawdown Circuit Breaker

**Status:** `[x]` Complete — 2026-04-29
**Goal:** Add a rolling-drawdown-triggered de-risking overlay that survives in production (recoverable, not monotonic).

**Deliverables:**

- [x] `src/csm/risk/drawdown.py` — extended with `rolling_drawdown(equity: pd.Series, window: int) -> pd.Series`
- [x] `src/csm/portfolio/drawdown_circuit_breaker.py` — `DrawdownCircuitBreaker` (standalone, following Phase 4.3/4.4 convention)
  - [x] `apply(weights, equity_curve, config, current_state, recovery_progress_days) -> tuple[pd.Series, CircuitBreakerResult]`
  - [x] Trips when `rolling_drawdown(window)` reaches threshold (default −20%)
  - [x] Tripped → equity fraction capped at `safe_mode_max_equity` (default 0.20)
  - [x] Recovers when rolling DD recovers above `recovery_threshold` (default −10%) for `recovery_confirm_days` (default 21)
  - [x] State machine: `NORMAL` → `TRIPPED` → `RECOVERING` → `NORMAL` with hysteresis
- [x] `DrawdownCircuitBreakerConfig` Pydantic: `enabled=True`, `window_days=60`, `trigger_threshold=-0.20`, `recovery_threshold=-0.10`, `recovery_confirm_days=21`, `safe_mode_max_equity=0.20`
- [x] `CircuitBreakerTripped` exception (for live-mode hard halt — backtest never raises, only logs)
- [x] `CircuitBreakerState` enum extended with `TRIPPED` and `RECOVERING`
- [x] Unit tests (27 cases): trip on synthetic equity curve, no trip below threshold, recovery after confirm period, re-trip, state machine determinism, empty equity/weights, disabled pass-through
- [x] All quality gates pass: ruff clean, mypy clean, 412/422 tests pass (10 pre-existing failures)

**Completion Notes:** Phase 4.5 implemented the standalone `DrawdownCircuitBreaker` at `src/csm/portfolio/drawdown_circuit_breaker.py` (deviating from the original PLAN.md path `src/csm/risk/circuit_breaker.py` to follow Phase 4.3/4.4 conventions). The module uses rolling N-day drawdown (not peak-to-trough) for natural recovery, a hysteresis-banded state machine preventing oscillation, and stateless design with state threaded by the caller. The rolling DD computation is a new method on `DrawdownAnalyzer` in `src/csm/risk/drawdown.py`. The pipeline overlay adapter is deferred to Phase 4.6.

---

### Phase 4.6 — Sector & Regime Constraint Engine

**Status:** `[ ]` Not started
**Goal:** Extract `MomentumBacktest._apply_sector_cap()` into `csm.portfolio.constraints` and wrap `RegimeDetector` as a portfolio-level overlay.

**Deliverables:**

- [ ] `src/csm/portfolio/constraints.py` — `SectorCapOverlay`, `PositionSizeOverlay`, `HoldingsCountOverlay`
  - [ ] `SectorCapOverlay.apply()` — equal-weight cap per sector (default 0.35); evicts lowest-ranked symbol(s) in overweight sector(s); guarantees `n_holdings ≥ n_holdings_min` (Phase 3.9 known issue documented in plan)
  - [ ] `PositionSizeOverlay.apply()` — clip individual weights to `[min_position, max_position]`; renormalises
  - [ ] `HoldingsCountOverlay.apply()` — enforces `n_holdings_min ≤ n ≤ n_holdings_max`
- [ ] `src/csm/risk/regime.py` — extend with `RegimeOverlay` wrapper
  - [ ] `apply(state: PortfolioState, ctx: OverlayContext) -> PortfolioState`
  - [ ] Reads `state.regime` (set by upstream `RegimeDetector`); applies safe-mode equity cap in BEAR / EARLY_BULL; full cash if `bear_full_cash=True` and EMA200 slope negative
- [ ] Constants: all thresholds from `BacktestConfig` exposed via `OverlayContext`
- [ ] Unit tests (≥ 10 cases): sector cap binds, holdings-min guard prevents under-trim, regime overlay caps equity in BEAR, full-cash trigger, parity with inline Phase 3.9 implementation
- [ ] Snapshot parity: full pipeline with overlays matching Phase 3.9 reproduces baseline equity curve to 1e-9

---

### Phase 4.7 — Execution Simulation & Trade List

**Status:** `[ ]` Not started
**Goal:** Produce a deterministic per-rebalance `TradeList` with realistic slippage. This is the artefact a future broker adapter will consume.

**Deliverables:**

- [ ] `src/csm/execution/__init__.py` — new package
- [ ] `src/csm/execution/trade_list.py` — Pydantic models
  - [ ] `Trade`: `symbol`, `side` (BUY/SELL/HOLD), `target_weight`, `current_weight`, `delta_weight`, `target_shares`, `delta_shares`, `notional_thb`, `expected_slippage_bps`, `participation_rate`, `capacity_violation: bool`
  - [ ] `TradeList`: list of `Trade` + summary aggregates (total turnover, total slippage cost, n_capacity_violations)
  - [ ] `ExecutionResult`: `TradeList` + post-execution realised equity fraction
- [ ] `src/csm/execution/slippage.py` — `SqrtImpactSlippageModel`
  - [ ] `estimate(notional_thb: float, adtv_thb: float) -> float` returns slippage in bps
  - [ ] Formula: `half_spread_bps + impact_coef × sqrt(participation_rate)`
- [ ] `src/csm/execution/simulator.py` — `ExecutionSimulator`
  - [ ] `simulate(state: PortfolioState, prices: pd.Series, volumes: pd.Series, current_positions: dict[str, int], config: ExecutionConfig) -> ExecutionResult`
  - [ ] Computes per-symbol delta shares; rounds to whole shares (configurable lot size)
  - [ ] Estimates slippage via injected slippage model
  - [ ] Marks `capacity_violation=True` if participation rate > `max_participation_rate`
- [ ] `ExecutionConfig` Pydantic: `aum_thb=200_000_000`, `lot_size=100`, `max_participation_rate=0.10`, `slippage_model: SlippageModelConfig`
- [ ] Backtest integration: `MomentumBacktest.run()` invokes `ExecutionSimulator` at each rebalance; trade lists collected into `BacktestResult.trade_lists: list[TradeList]`
- [ ] Unit tests (≥ 14 cases): trade list correctness on canned input, slippage formula, capacity violation flag, lot-size rounding, hold detection (delta below threshold), full backtest produces N trade lists for N rebalance dates
- [ ] Performance: simulating one trade list on 60-name portfolio < 5ms

---

### Phase 4.8 — Portfolio Optimization Notebook & Walk-Forward Gate

**Status:** `[ ]` Not started
**Goal:** Phase 4 sign-off notebook and CI gate specification.

**Deliverables:**

- [ ] `notebooks/04_portfolio_optimization.ipynb` — markdown cells in Thai per project convention
  - [ ] **Section 1**: Setup, data loading, baseline (Phase 3.9 config) reference
  - [ ] **Section 2**: Weighting scheme comparison — `EQUAL` vs `VOL_TARGET` vs `INVERSE_VOL` vs `MIN_VARIANCE`; equity curves, Sharpe / DD / turnover table
  - [ ] **Section 3**: Vol scaling overlay sensitivity — `vol_target ∈ {0.10, 0.12, 0.15, 0.18, 0.20}` × `cap ∈ {1.0, 1.25, 1.5}`
  - [ ] **Section 4**: Drawdown circuit breaker stress test — synthetic adverse paths + historical 2008 / 2013 / 2020 SET drawdowns; verify breaker trips and recovers
  - [ ] **Section 5**: Capacity sweep — AUM ∈ {50M, 100M, 200M, 500M, 1B} THB; report % trades capped, aggregate slippage cost, effective Sharpe at each AUM
  - [ ] **Section 6**: Sector exposure over time, turnover decomposition (selection turnover vs reweighting turnover)
  - [ ] **Section 7**: Walk-forward OOS — full overlay stack across 5 folds; report IS vs OOS Sharpe per fold; PASS/FAIL gate
  - [ ] **Section 8**: Final config decision cell — locks `BacktestConfig` defaults for Phase 5; prints PASS/FAIL for all 7 exit criteria
  - [ ] **Section 9**: Monte Carlo Portfolio Robustness — luck-vs-skill validation
    - [ ] **9a — Random Weight Allocation Test**: at each rebalance, replace `WeightOptimizer.compute()` output with N=10,000 random long-only weight vectors over the top-quintile selection (Dirichlet sampling, reusing `WeightOptimizer._monte_carlo_optimize()` infrastructure from Phase 4.2). Run a full backtest per sample. Report the distribution of CAGR / Sharpe / Max DD across samples; visualise as a histogram with the Phase 3.9 equal-weight result and the Phase 4.2 max-Sharpe result marked. **PASS** if median CAGR > SET-TRI median CAGR over the same window AND ≥ 90% of random-weight paths produce positive CAGR. The test isolates *selection edge* from *weighting choice* and answers whether the Phase 3.9 12.52% CAGR is structural or an artefact of the equal-weight choice.
    - [ ] **9b — Path Dependency / Sequence-of-Returns Test**: hold the per-symbol *return distribution* constant but permute its time-ordering. Use circular block-bootstrap (block size = 21 trading days, N=1,000 paths) on each symbol's daily returns, recompute the equity curve under the full Phase 4 overlay stack, and verify the Phase 4.5 Drawdown Circuit Breaker `NORMAL → TRIPPED → RECOVERING → NORMAL` transitions still occur correctly across the resampled paths. Report: % of paths the breaker tripped at least once; mean recovery time; distribution of terminal CAGR. **PASS** if the breaker trips on ≥ 95% of synthetically adverse paths (DD > −20% in the path) and recovers on ≥ 90% of those trips.
    - [ ] Section 9 markdown cells in Thai per project convention; reuses `monte_carlo_frontier()` and `WeightOptimizer._monte_carlo_optimize()` from `src/csm/portfolio/optimizer.py` (Phase 4.2)
    - [ ] Performance budget: random-weight backtest sweep ≤ 10 minutes on a 60-name × 12-year history at N=10,000; bootstrap path sweep ≤ 5 minutes at N=1,000
- [ ] `docs/plans/phase4_portfolio_construction/walk_forward_ci_gate.md` — spec for Phase 5 CI integration: `pytest -m walk_forward` runs full OOS validation, fails if any fold OOS Sharpe ≤ 0 or IS/OOS Sharpe ratio > 1.5

**Notebook is the Phase 4 exit gate.** Section 8 prints PASS/FAIL across all 13 success criteria (rows #1–#13 in Success Criteria), including the Section 9 luck-vs-skill checks.

---

## Data Models

### `PortfolioState`

```python
class PortfolioState(BaseModel):
    asof: pd.Timestamp
    target_weights: dict[str, float]  # symbol → weight, sums ≤ 1.0
    equity_fraction: float             # in [0, vol_scale_cap]
    regime: RegimeState
    breaker_state: CircuitBreakerState  # NORMAL | TRIPPED | RECOVERING
    journal: list[OverlayJournalEntry]
```

### `OverlayContext`

```python
class OverlayContext(BaseModel):
    prices_window: pd.DataFrame    # Lookback window for vol / DD computations
    volumes_window: pd.DataFrame
    index_prices_window: pd.Series
    sector_map: dict[str, str]
    backtest_config: BacktestConfig
    equity_curve_to_date: pd.Series  # For DD computations
```

### `OverlayJournalEntry`

```python
class OverlayJournalEntry(BaseModel):
    overlay: str                     # e.g. "VolScalingOverlay"
    asof: pd.Timestamp
    decision: str                    # human-readable
    inputs: dict[str, float]         # numerical inputs to the decision
    outputs: dict[str, float]        # what the overlay changed
```

### `Trade`

```python
class Trade(BaseModel):
    symbol: str
    side: TradeSide                  # BUY | SELL | HOLD
    target_weight: float
    current_weight: float
    delta_weight: float
    target_shares: int
    delta_shares: int
    notional_thb: float
    expected_slippage_bps: float
    participation_rate: float
    capacity_violation: bool = False
```

### `BacktestConfig` additions (Phase 4)

```python
# New fields (in addition to Phase 3.9):
weight_scheme: WeightScheme = WeightScheme.VOL_TARGET
vol_scaling_enabled: bool = True   # FLIPPED from False
optimizer_config: OptimizerConfig | None = None
vol_scaling_config: VolScalingConfig | None = None
capacity_config: CapacityConfig | None = None
circuit_breaker_config: CircuitBreakerConfig | None = None
execution_config: ExecutionConfig | None = None
```

When the `*_config` fields are `None`, defaults from each overlay's own config class apply. This keeps `BacktestConfig` backwards-compatible with Phase 3.9 callers.

---

## Error Handling Strategy

| Scenario | Behaviour |
|---|---|
| `WeightOptimizer.compute(scheme=MIN_VARIANCE)` solver fails to converge | Log warning; fall back to `INVERSE_VOL`; record fallback in journal |
| `WeightOptimizer` produces negative weight | Raise `OptimizationError`; this is a code bug, not a runtime condition |
| `VolScalingOverlay` encounters zero realised vol | Return `equity_fraction = vol_scale_cap` (treat as "no risk to scale") |
| `CapacityOverlay` encounters zero ADV | Drop the symbol from the trade list; log warning; record in journal |
| `DrawdownCircuitBreaker` trip in **backtest mode** | Apply safe-mode equity; log trip; continue. **Never raise.** |
| `DrawdownCircuitBreaker` trip in **live mode** (Phase 5 future) | Raise `CircuitBreakerTripped`; halt order submission |
| `ExecutionSimulator` cannot meet target weight (insufficient ADV at any AUM) | Generate trade with `capacity_violation=True`; do not raise |
| `SectorCapOverlay` would trim below `n_holdings_min` | Stop trimming; log warning; record sector cap was relaxed |
| `PortfolioState.target_weights.sum() > 1.0 + 1e-6` | Raise `ConstraintViolationError` — invariant violated, code bug |
| Overlay journal entry missing for an applied overlay | Raise `RuntimeError` in tests; in prod, log error and continue |

---

## Testing Strategy

### Coverage Target

≥ 90% line coverage on all new modules under `csm.portfolio.*`, `csm.risk.*`, `csm.execution.*`. ≥ 95% coverage on the overlay `apply()` methods specifically (these are the production hot paths).

### Snapshot Parity Tests (the most important tests in Phase 4)

`tests/unit/research/test_backtest_phase4_parity.py`:

- [ ] `test_phase39_baseline_equity_curve_unchanged` — full Phase 4 pipeline configured to match Phase 3.9 (vol_scaling=False, no capacity, no circuit breaker, equal-weight) reproduces Phase 3.8/3.9 baseline equity curve to 1e-9 absolute tolerance
- [ ] `test_phase39_baseline_metrics_unchanged` — same config produces identical CAGR, Sharpe, max DD, win rate (1e-6 tolerance)
- [ ] `test_phase39_baseline_holdings_unchanged` — same config produces identical holdings sequence at every rebalance date

These tests are the gate for the refactor sub-phases (4.1, 4.2, 4.6). They must pass before any of the new-overlay sub-phases (4.3–4.5, 4.7) are merged.

### Mocking Strategy

- Overlay tests: synthesise `PortfolioState` and `OverlayContext` with deterministic inputs; assert deterministic outputs
- Slippage tests: pure-function, no mocking needed
- Execution simulator tests: inject deterministic slippage model; assert per-trade fields
- Pipeline tests: chain mock overlays that record call order; assert composition order matches spec

### Integration Tests

- `tests/integration/test_full_phase4_backtest.py` — runs full Phase 4 backtest with all overlays enabled; asserts: Sharpe ≥ 0.70, Max DD ≥ −25%, all walk-forward folds OOS Sharpe > 0
- Marked `@pytest.mark.integration`; skipped in default CI; run on PR merge

### Test File Map

| Module | Test file |
|---|---|
| `src/csm/portfolio/construction.py` | `tests/unit/portfolio/test_construction.py` |
| `src/csm/portfolio/optimizer.py` | `tests/unit/portfolio/test_optimizer.py` |
| `src/csm/portfolio/constraints.py` | `tests/unit/portfolio/test_constraints.py` |
| `src/csm/portfolio/pipeline.py` | `tests/unit/portfolio/test_pipeline.py` |
| `src/csm/portfolio/state.py` | `tests/unit/portfolio/test_state.py` |
| `src/csm/portfolio/vol_scaler.py` | `tests/unit/portfolio/test_vol_scaler.py` |
| `src/csm/portfolio/liquidity_overlay.py` | `tests/unit/portfolio/test_liquidity_overlay.py` |
| `src/csm/risk/circuit_breaker.py` | `tests/unit/risk/test_circuit_breaker.py` |
| `src/csm/execution/simulator.py` | `tests/unit/execution/test_simulator.py` |
| `src/csm/execution/slippage.py` | `tests/unit/execution/test_slippage.py` |
| `src/csm/execution/trade_list.py` | `tests/unit/execution/test_trade_list.py` |

---

## Success Criteria

| # | Criterion | Measure |
|---|---|---|
| 1 | Snapshot parity | Phase 3.9 config produces byte-identical equity curve (1e-9) |
| 2 | Sharpe with full overlay stack | ≥ 0.70 (vs Phase 3.8 baseline 0.663) |
| 3 | Max drawdown with full overlay stack | ≤ −25% (vs Phase 3.8 baseline −31%) |
| 4 | Annualised turnover | ≤ 180% |
| 5 | Liquidity pass rate | ≥ 95% of target trades fit within 10% ADV at AUM = 200M THB |
| 6 | Sector exposure | ≤ 35% at every rebalance, no exceptions |
| 7 | Walk-forward OOS Sharpe | > 0 across all 5 folds; IS/OOS Sharpe ratio < 1.5 |
| 8 | Test coverage | ≥ 90% on new `csm.{portfolio,risk,execution}` modules |
| 9 | Type / lint / test gates | `uv run mypy src/`, `uv run ruff check .`, `uv run pytest tests/ -v -m "not integration"` all green |
| 10 | Notebook sign-off | `04_portfolio_optimization.ipynb` Section 8 prints PASS for all 7 exit criteria |
| 11 | Trade list determinism | Two runs with same seed produce identical `TradeList`s |
| 12 | Circuit breaker recovery | Stress test confirms breaker trips on synthetic −25% DD and recovers per spec |
| 13 | Monte Carlo robustness | Section 9a: median random-weight CAGR > SET-TRI median over the same window AND ≥ 90% of random-weight paths produce positive CAGR. Section 9b: circuit breaker trips on ≥ 95% of bootstrap paths whose DD breaches −20% and recovers on ≥ 90% of trips. |

---

## Future Enhancements

- **VaR / CVaR position limits** — historical or parametric VaR caps per position and per portfolio (Phase 9)
- **Multi-strategy aggregation** — combine momentum portfolio with value / quality portfolios under a unified risk budget (Phase 9)
- **Calibrated slippage model** — replace default sqrt-impact coefficients with empirically calibrated values from SET execution data (Phase 9)
- **Broker connectors** — paper broker stub + SETTRADE adapter consuming `TradeList` (post-Phase 5)
- **Live circuit breaker** — wire `CircuitBreakerTripped` exception into the API to halt order submission (Phase 5)
- **Factor neutralisation** — extend `constraints.py` with style / value / size factor exposure caps (Phase 9)
- **Dynamic regime-conditional vol scaling** — `vol_target` varies with detected regime (BULL → 18%, BEAR → 10%) — flagged as a future enhancement on the back of Phase 4 sensitivity work
- **Walk-forward CI integration** — `pytest -m walk_forward` runs full OOS validation on every PR; integrated into Phase 8 CI

---

## Commit & PR Templates

### Commit Message (Plan — this commit)

```
feat(plan): add master plan for phase 4 portfolio construction based on phase 3.9 stability metrics
```

### Commit Messages (per sub-phase, on implementation)

```
feat(portfolio): add PortfolioConstructor with quintile select + buffer + exit floor (Phase 4.1)

- PortfolioConstructor.select() promoted from inline _select_holdings()
- SelectionResult Pydantic model
- Snapshot parity test: Phase 3.9 equity curve byte-identical
```

```
feat(portfolio): expand WeightOptimizer with vol_target, inverse_vol, min_variance (Phase 4.2)

- 4 weighting schemes via WeightScheme enum
- Min-variance solver with inverse-vol fallback
- Position floor / cap enforcement
```

```
feat(risk): add VolScalingOverlay; lock vol_scaling=True as default (Phase 4.3)

- Extracts MomentumBacktest._apply_vol_scaling() into csm.risk.vol_scaling
- BacktestConfig.vol_scaling_enabled default flipped to True
- Phase 3.9 baseline reproducible via vol_scaling_enabled=False
```

```
feat(risk): add CapacityOverlay with ADV participation cap (Phase 4.4)

- Per-position notional capped at adv_cap_pct × ADV_thb (default 10%)
- Strategy capacity curve helper for AUM sensitivity
```

```
feat(risk): add DrawdownCircuitBreaker with rolling DD trigger (Phase 4.5)

- Rolling 60d DD threshold (default -20%) → safe-mode equity (default 20%)
- State machine: NORMAL → TRIPPED → RECOVERING → NORMAL
- CircuitBreakerTripped exception (live-mode only)
```

```
refactor(portfolio): extract sector cap and regime gate as Constraint overlays (Phase 4.6)

- SectorCapOverlay, PositionSizeOverlay, HoldingsCountOverlay in csm.portfolio.constraints
- RegimeOverlay wraps RegimeDetector for portfolio-pipeline use
- Snapshot parity preserved
```

```
feat(execution): add ExecutionSimulator with sqrt-impact slippage and TradeList output (Phase 4.7)

- Per-rebalance TradeList with target/current/delta weights, shares, slippage, capacity flag
- Square-root market-impact slippage model + half-spread
- BacktestResult.trade_lists collected
```

```
feat(notebooks): add 04_portfolio_optimization.ipynb — Phase 4 sign-off (Phase 4.8)

- Weighting scheme comparison, vol scaling sensitivity, circuit breaker stress test
- Capacity sweep across AUM grid; walk-forward OOS report
- Final config decision cell with PASS/FAIL gate
```

### PR Description Template

```markdown
## Summary

Phase 4 — Portfolio Construction & Risk Management. Promotes Phase 3.9 inline backtest logic into composable, testable, live-trading-ready modules and adds three new risk overlays (volatility scaling, liquidity/capacity, drawdown circuit breaker) plus an execution simulator producing deterministic trade lists with realistic slippage.

- `PortfolioConstructor` + `WeightOptimizer` (4 schemes) + `PortfolioPipeline` overlay orchestrator
- `VolScalingOverlay` (locked on by default), `CapacityOverlay` (ADV% cap), `DrawdownCircuitBreaker` (rolling DD)
- `SectorCapOverlay`, `PositionSizeOverlay`, `HoldingsCountOverlay`, `RegimeOverlay`
- `ExecutionSimulator` + sqrt-impact slippage + `TradeList` output
- Snapshot parity tests guarantee byte-identical reproduction of Phase 3.9 equity curve when overlays disabled
- `notebooks/04_portfolio_optimization.ipynb` — Phase 4 sign-off

## Test plan

- [ ] `uv run pytest tests/unit/ -v` — all unit tests pass
- [ ] `uv run pytest tests/unit/research/test_backtest_phase4_parity.py -v` — snapshot parity ≤ 1e-9
- [ ] `uv run pytest tests/integration/test_full_phase4_backtest.py -v -m integration` — Sharpe ≥ 0.70, Max DD ≥ −25%
- [ ] `uv run mypy src/` — exits 0
- [ ] `uv run ruff check .` — exits 0
- [ ] Manual: open `04_portfolio_optimization.ipynb`, run all cells, confirm Section 8 PASS for all 7 exit criteria
```
