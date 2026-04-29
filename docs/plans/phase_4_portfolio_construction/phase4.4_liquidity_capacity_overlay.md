# Phase 4.4 — Liquidity & Capacity Overlay

**Feature:** Per-position ADTV Participation Cap & Strategy Capacity Curve for the SET Cross-Sectional Momentum Strategy
**Branch:** `feature/phase-4-portfolio-construction`
**Created:** 2026-04-29
**Status:** Complete
**Completed:** 2026-04-29
**Depends On:** Phase 4.3 (Volatility Scaling Engine — complete)

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

Phase 4.4 adds a per-position ADV-participation cap to the portfolio construction pipeline. Phase 3.9 has a binary ADTV hard filter (symbols below 5M THB are dropped), but no continuous sizing constraint — at AUM > ~100M THB, naive equal-weighting on ~50 names will hit thinly traded SET symbols hard. This overlay caps each position's notional at `adv_cap_pct × ADV_thb` (default 10% participation), reduces oversized positions, and holds excess as cash. It also provides a strategy capacity curve helper for AUM sensitivity analysis.

### Parent Plan Reference

- `docs/plans/phase_4_portfolio_construction/PLAN.md`

### Key Deliverables

1. **`LiquidityConfig` Pydantic model** — 4 fields: `enabled`, `adv_cap_pct`, `adtv_lookback_days`, `assumed_aum_thb`
2. **`LiquidityResult` Pydantic model** — 6 fields: `effective_equity_fraction`, `n_capped`, `n_total`, `n_zero_adtv`, `per_position`, totals
3. **`PositionLiquidityInfo` Pydantic model** — per-symbol diagnostics with 8 fields
4. **`LiquidityOverlay` class** — `apply()` and `_compute_adtv()` static method
5. **`compute_capacity_curve()` standalone function** — AUM sensitivity sweep
6. **Unit tests** — 27 cases across 5 test classes

---

## AI Prompt

The following prompt was used to generate this phase:

```
🎯 Objective
Design and implement Phase 4.4 — Liquidity & Capacity Overlay for the SET
Cross-Sectional Momentum Strategy, following the project's architectural, type
safety, and documentation standards. Deliver a detailed implementation plan as
a markdown file, then implement the liquidity overlay module, comprehensive
tests, and update all relevant documentation and progress tracking files.

📋 Context
- The project is a production-grade, type-safe, async-first Python library for
  SET momentum strategies.
- Phase 4.4 focuses on building a Liquidity & Capacity Overlay that caps per-
  position notional at a configurable fraction of ADV, integrates with the
  Phase 4.3 VolatilityScaler output, and provides a strategy capacity curve.
- The previous phases (4.1-4.3) delivered PortfolioConstructor, WeightOptimizer,
  and VolatilityScaler as standalone modules.
- Documentation and progress tracking are maintained in markdown files under
  docs/plans/phase_4_portfolio_construction/.
- All code must use explicit type annotations, Pydantic models for configs/
  results, and comprehensive tests.

🔧 Requirements
- Carefully read and understand:
  - docs/plans/phase_4_portfolio_construction/PLAN.md (focus on Phase 4.4)
  - docs/plans/phase_4_portfolio_construction/phase4.3_volatility_scaling_engine.md
- Before coding, create a detailed implementation plan for Phase 4.4 as
  docs/plans/phase_4_portfolio_construction/phase4.4_liquidity_capacity_overlay.md,
  including the full prompt used.
- Implement the Liquidity & Capacity Overlay in src/csm/portfolio/liquidity_overlay.py:
  - Accepts raw weights, price/volume history, and a Pydantic config.
  - Computes and enforces per-asset and portfolio-level liquidity/capacity constraints.
  - Returns adjusted weights and a Pydantic result model with constraint diagnostics.
  - Handles edge cases (illiquid assets, empty input, extreme constraints) gracefully.
  - Uses explicit type annotations and Pydantic validation throughout.
- Write ≥10 unit tests in tests/unit/portfolio/test_liquidity_overlay.py:
  - Cover constraint logic, edge cases, and integration with upstream optimizer/scaler output.
- Update docs/plans/phase_4_portfolio_construction/PLAN.md and
  phase4.4_liquidity_capacity_overlay.md with progress notes, completion status,
  and any issues encountered.
- Ensure all code passes ruff, mypy, and pytest gates.
- Commit all changes with a clear, standards-compliant message.
```

---

## Scope

### In Scope

| Component | Description | Status |
|-----------|-------------|--------|
| `LiquidityConfig` Pydantic model | 4 fields with validation | Complete |
| `LiquidityResult` Pydantic model | 6 fields for overlay metadata | Complete |
| `PositionLiquidityInfo` Pydantic model | 8 fields per-symbol diagnostics | Complete |
| `LiquidityOverlay.apply()` | Main entry point: weights + prices + volumes → adjusted weights + result | Complete |
| `LiquidityOverlay._compute_adtv()` | Static helper: close × volume mean over lookback | Complete |
| `compute_capacity_curve()` | Standalone function: AUM grid sweep | Complete |
| `__init__.py` exports | Add 5 new symbols | Complete |
| Unit tests | 27 cases in 5 test classes | Complete |
| Plan document | phase4.4_liquidity_capacity_overlay.md | Complete |
| PLAN.md update | Phase 4.4 status → Complete | Complete |

### Out of Scope

- Pipeline overlay adapter consuming `PortfolioState` (deferred to Phase 4.6)
- Wiring into `MomentumBacktest.run()` (deferred to Phase 4.6 refactor)
- Per-position notional cap independent of ADV (e.g., absolute THB cap) — deferred to Phase 9
- Calibrated market-impact slippage model — deferred to Phase 4.7

---

## Design Decisions

### 1. Standalone module, not overlay

The module sits at `src/csm/portfolio/liquidity_overlay.py` and accepts raw `pd.Series` weights + `pd.DataFrame` prices + `pd.DataFrame` volumes, returning `(pd.Series, LiquidityResult)`. It does NOT implement the `apply(state, ctx) -> state` overlay protocol. The pipeline overlay adapter (consuming `PortfolioState`) will wrap this module in Phase 4.6.

**Rationale:** Keeps the liquidity math pure and testable without pipeline state coupling. Follows the same pattern as `VolatilityScaler` (Phase 4.3) which is also a standalone module.

### 2. Same ADTV formula as `_apply_adtv_filter`

The `_compute_adtv()` static method uses the same formula as `MomentumBacktest._apply_adtv_filter()` in `backtest.py:229-259`: `ADTV = mean(close × volume)` over the trailing lookback window. This ensures consistency with the Phase 3.9 binary filter.

**Rationale:** The binary ADTV filter (drop symbols < 5M THB) and the continuous participation cap (scale symbols exceeding 10% of ADV) compute ADTV identically. Using the same formula prevents situations where a symbol passes the binary filter but gets a different ADTV from the scaler.

### 3. Illiquid assets are zeroed, not dropped

Symbols with zero/NaN ADTV (missing from volume or price data) have their weight zeroed but remain in the result with `cap_binding=True` and `participation_rate=inf`. They are NOT dropped from the weights Series.

**Rationale:** Dropping symbols changes the index length, breaking the homogeneous-output contract of the overlay pipeline. Zeroing preserves the index shape while recording the decision in `per_position` diagnostics.

### 4. No iterative redistribution

When a position is capped, its excess weight is simply held as cash (reduces `effective_equity_fraction`). The excess is NOT redistributed to uncapped positions.

**Rationale:** Redistributing to uncapped positions can create a cascading cap effect (position A capped → excess to B → B now exceeds cap → excess to C → ...). This iterative approach adds complexity, creates non-determinism risk, and is semantically questionable — if a position can't absorb its target allocation, forcing other positions to absorb more isn't necessarily better. Simple cash reserve is the conservative choice.

### 5. Two-part approach: no renormalization of adjusted weights

Adjusted weights are NOT renormalized to sum to 1.0. They sum to `effective_equity_fraction` (≤ 1.0). The difference (1.0 − `effective_equity_fraction`) is the cash reserve.

**Rationale:** This preserves the signal from each position: a weight of 0.15 that gets capped to 0.02 is clearly that position's liquidity-constrained allocation. Renormalizing would obscure this signal. The equity fraction is passed forward in the pipeline so downstream overlays (vol scaler, circuit breaker) can apply their own multipliers.

### 6. `assumed_aum_thb` is config-level, not a separate parameter

The AUM is a config field, not a runtime parameter. This keeps the `apply()` signature clean and follows the Phase 4.3 pattern where `target_annual` is a config field.

---

## Implementation Steps

1. Create `src/csm/portfolio/liquidity_overlay.py` with `LiquidityConfig`, `LiquidityResult`, `PositionLiquidityInfo`, `LiquidityOverlay`, `compute_capacity_curve`
2. Update `src/csm/portfolio/__init__.py` — add imports and `__all__` entries for 5 new symbols
3. Create `tests/unit/portfolio/test_liquidity_overlay.py` — 27 test cases in 5 test classes
4. Run ruff auto-fix for import ordering
5. Run verification: ruff → mypy → pytest (27 new + full suite regression)
6. Update PLAN.md — mark Phase 4.4 complete
7. Create `phase4.4_liquidity_capacity_overlay.md` — this document

---

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/csm/portfolio/liquidity_overlay.py` | CREATE | `LiquidityConfig`, `LiquidityResult`, `PositionLiquidityInfo`, `LiquidityOverlay`, `compute_capacity_curve` |
| `src/csm/portfolio/__init__.py` | MODIFY | Add imports + `__all__` for 5 new symbols |
| `tests/unit/portfolio/test_liquidity_overlay.py` | CREATE | 27 tests in 5 classes |
| `docs/plans/phase_4_portfolio_construction/PLAN.md` | MODIFY | Mark Phase 4.4 complete |
| `docs/plans/phase_4_portfolio_construction/phase4.4_liquidity_capacity_overlay.md` | CREATE | This plan document |

---

## Success Criteria

- [x] `LiquidityConfig` Pydantic model with 4 validated fields
- [x] `LiquidityResult` Pydantic model with 6 fields
- [x] `PositionLiquidityInfo` Pydantic model with 8 fields
- [x] `LiquidityOverlay.apply()` caps positions when participation > adv_cap_pct
- [x] `LiquidityOverlay.apply()` passes through unchanged when disabled
- [x] `LiquidityOverlay.apply()` handles empty weights gracefully
- [x] Zero-ADTV symbols are zeroed with diagnostic recording
- [x] `_compute_adtv()` matches manual `mean(close × volume)` computation
- [x] Adjusted weights sum to `effective_equity_fraction` (invariant)
- [x] Capacity curve: n_capped monotonic in AUM
- [x] Capacity curve: equity fraction non-increasing in AUM
- [x] Capacity curve: default grid produces 20 log-spaced points
- [x] ruff exits 0
- [x] mypy exits 0
- [x] All 27 tests pass
- [x] Full unit test suite passes (384/390, 6 pre-existing failures)

---

## Completion Notes

### Summary

Phase 4.4 implemented the standalone `LiquidityOverlay` module at `src/csm/portfolio/liquidity_overlay.py`. The module computes per-symbol ADTV (mean of close × volume over 63 trailing bars), checks each position's participation rate against the configurable cap, caps oversized positions, and returns adjusted weights with full per-position diagnostics. The `compute_capacity_curve()` helper sweeps an AUM grid to report strategy capacity characteristics. All quality gates pass and no regressions were introduced.

### What Was Implemented

**Pydantic Models:**
- `LiquidityConfig`: 4 fields with validation (enabled, adv_cap_pct, adtv_lookback_days, assumed_aum_thb)
- `LiquidityResult`: 6 fields (effective_equity_fraction, n_capped, n_total, n_zero_adtv, per_position, totals)
- `PositionLiquidityInfo`: 8 fields per-symbol (symbol, adtv_thb, target_notional, capped_notional, original_weight, adjusted_weight, participation_rate, cap_binding)

**LiquidityOverlay Methods:**
- `apply(weights, prices, volumes, config) -> tuple[pd.Series, LiquidityResult]` — main entry point
- `_compute_adtv(prices, volumes, lookback_days) -> pd.Series` — static helper using same formula as `_apply_adtv_filter`

**Standalone Function:**
- `compute_capacity_curve(weights, prices, volumes, config, aum_grid) -> pd.DataFrame` — AUM grid sweep

**Tests:** 27 cases in 5 test classes covering config validation, all constraint edge cases, capacity curve monotonicity, and illiquid asset handling.

### Issues Encountered

1. **Import ordering** — ruff auto-fixed I001 on `__init__.py`, `liquidity_overlay.py`, and `test_liquidity_overlay.py`. The `Optional[]` type annotations (UP045) were also auto-fixed to `X | None` syntax.

### Deviation from PLAN.md

The original PLAN.md specified `src/csm/risk/capacity.py` with a `CapacityOverlay` that consumes `PortfolioState`. The implementation uses `src/csm/portfolio/liquidity_overlay.py` with a standalone `LiquidityOverlay` that accepts raw pandas objects. This follows the Phase 4.3 pattern where `VolatilityScaler` was placed in `src/csm/portfolio/` rather than `src/csm/risk/`. The overlay adapter will be created in Phase 4.6 when the `PortfolioPipeline` is assembled.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.7)
**Status:** Complete
**Completed:** 2026-04-29
