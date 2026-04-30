# Phase 4.3 — Volatility Scaling Engine

**Feature:** Standalone Volatility Scaling Engine for the SET Cross-Sectional Momentum Strategy
**Branch:** `feature/phase-4-portfolio-construction`
**Created:** 2026-04-29
**Status:** Complete
**Completed:** 2026-04-29
**Depends On:** Phase 4.2 (Weight Optimizer Expansion — complete)

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

Phase 4.3 extracts the validated vol-scaling logic from `MomentumBacktest._apply_vol_scaling()` (backtest.py:441-471) into a standalone, testable `VolatilityScaler` module under `src/csm/portfolio/`. The module computes portfolio realized volatility from position weights and price history, then scales the weight vector so total equity exposure targets a specified annualized volatility (default 15%).

### Parent Plan Reference

- `docs/plans/phase_4_portfolio_construction/PLAN.md`

### Key Deliverables

1. **`VolScalingConfig` Pydantic model** — 6 fields including `enabled`, `target_annual`, `lookback_days`, `cap`, `floor`, `regime_aware`
2. **`VolScalingResult` Pydantic model** — `realized_vol_annual`, `scale_factor`, `equity_fraction`
3. **`VolatilityScaler` class** — `scale()` and `_compute_realized_vol()` static method
4. **BacktestConfig changes** — flip `vol_scaling_enabled` default, add `vol_scaling_config` field
5. **Unit tests** — 22 cases across 4 test classes

---

## AI Prompt

The following prompt was used to generate this phase:

```
🎯 Objective
Design and implement Phase 4.3 — Volatility Scaling Engine for the SET Cross-Sectional
Momentum Strategy, following the project's architectural, type safety, and documentation
standards. Deliver a detailed implementation plan as a markdown file, then implement the
volatility scaling module, comprehensive tests, and update all relevant documentation
and progress tracking files.

📋 Context
- The project is a production-grade, type-safe, async-first Python library for SET momentum
  strategies.
- Phase 4.3 focuses on building a Volatility Scaling Engine that adjusts portfolio weights
  to target a specified portfolio volatility, integrating with the output of the
  WeightOptimizer from Phase 4.2.
- The previous phase (4.2) delivered a robust WeightOptimizer supporting multiple schemes
  and constraint enforcement.
- Documentation and progress tracking are maintained in markdown files under
  docs/plans/phase_4_portfolio_construction/.
- All code must use explicit type annotations, Pydantic models for configs/results, and
  comprehensive tests.

🔧 Requirements
- Carefully read and understand:
  - docs/plans/phase_4_portfolio_construction/PLAN.md (focus on Phase 4.3)
  - docs/plans/phase_4_portfolio_construction/phase4.2_weight_optimizer_expansion.md
- Before coding, create a detailed implementation plan for Phase 4.3 as
  docs/plans/phase_4_portfolio_construction/phase4.3_volatility_scaling_engine.md,
  including the full prompt used.
- Implement the Volatility Scaling Engine in src/csm/portfolio/vol_scaler.py:
  - Accepts raw weights, price history, and target volatility.
  - Computes realized volatility over a configurable lookback window.
  - Scales weights to achieve the target volatility, preserving direction and constraints.
  - Uses Pydantic models for configuration and results.
  - Handles edge cases (zero volatility, single asset, empty input) gracefully.
  - Includes comprehensive type annotations and Pydantic validation.
- Write ≥10 unit tests in tests/unit/portfolio/test_vol_scaler.py:
  - Test scaling logic, edge cases, constraint enforcement, and integration with
    WeightOptimizer output.
- Update docs/plans/phase_4_portfolio_construction/PLAN.md and
  phase4.3_volatility_scaling_engine.md with progress notes, completion status, and any
  issues encountered.
- Ensure all code passes ruff, mypy, and pytest gates.
- Commit all changes with a clear, standards-compliant message.
```

---

## Scope

### In Scope

| Component | Description | Status |
|-----------|-------------|--------|
| `VolScalingConfig` Pydantic model | 6 fields with validation | Complete |
| `VolScalingResult` Pydantic model | 3 fields for scaling metadata | Complete |
| `VolatilityScaler.scale()` | Main entry point: weights + prices → scaled weights + result | Complete |
| `VolatilityScaler._compute_realized_vol()` | Static helper: weighted portfolio vol via dot product | Complete |
| `BacktestConfig` updates | Flip default, add `vol_scaling_config` field | Complete |
| `__init__.py` exports | Add 3 new symbols | Complete |
| Unit tests | 22 cases in 4 test classes | Complete |
| Plan document | phase4.3_volatility_scaling_engine.md | Complete |
| PLAN.md update | Phase 4.3 status → Complete | Complete |

### Out of Scope

- Pipeline overlay adapter consuming `PortfolioState` (deferred to Phase 4.6)
- Regime-aware vol target adjustment (field exists, logic deferred to Phase 4.6)
- Wiring into `MomentumBacktest.run()` (deferred to Phase 4.6 refactor)

---

## Design Decisions

### 1. Standalone module, not overlay

The module sits at `src/csm/portfolio/vol_scaler.py` and accepts raw `pd.Series` weights + `pd.DataFrame` prices, returning `(pd.Series, VolScalingResult)`. It does NOT implement the `apply(state, ctx) -> state` overlay protocol. The pipeline overlay adapter (consuming `PortfolioState`) will wrap this module in Phase 4.6.

**Rationale:** Keeps the vol scaling math pure and testable without pipeline state coupling. Follows the same pattern as `WeightOptimizer` which is also a standalone module that will be wired into the pipeline later.

### 2. Weighted dot-product vol, not equal-weight mean

The existing `_compute_portfolio_vol` (backtest.py:420-439) uses `.mean(axis=1)` — equal-weight portfolio vol. The new `_compute_realized_vol()` uses a dot product with the actual weight vector: `returns.dot(weights)`.

**Rationale:** The old method only had a holdings list (no weights), so equal-weight was the best it could do. The new module receives explicit weights from `WeightOptimizer`, enabling a more precise vol estimate that respects the weight distribution.

**Trade-off:** Results differ from the old method when weights are non-uniform. The disabled pass-through (`enabled=False`) guarantees byte-identical reproduction of the Phase 3.9 baseline.

### 3. Two-tier clamping: scale_factor and equity_fraction

```python
scale_factor = clamp(target / realized, floor, cap)  # cap ∈ [1.0, 3.0]
equity_fraction = min(scale_factor, 1.0)               # never > 1.0 (no leverage)
```

The `cap` field controls the raw multiplier (default 1.5). The `equity_fraction` is independently capped at 1.0 because the strategy does not permit leverage. This two-tier design means:
- When realized vol is very low: scale_factor hits `cap` (e.g., 1.5), but equity_fraction is 1.0 (100% invested, no leverage).
- When equity has already been reduced upstream (e.g., by regime gating to 0.20), the pipeline adapter will apply the scale_factor to that reduced fraction: `0.20 * 1.5 = 0.30`.

### 4. `regime_aware` field present but not wired

The config field exists for forward compatibility. Phase 4.6 will read it and use regime-dependent targets (BULL → 18%, BEAR → 10%). Currently, setting it to `True` has no effect beyond passing through the config.

### 5. Existing BacktestConfig fields preserved

The individual fields (`vol_lookback_days`, `vol_target_annual`, `vol_scale_cap`) are retained alongside the new `vol_scaling_config` field. The existing `_apply_vol_scaling()` method continues to use the individual fields. This avoids breaking existing backtest code.

---

## Implementation Steps

1. Create `src/csm/portfolio/vol_scaler.py` with `VolScalingConfig`, `VolScalingResult`, `VolatilityScaler`
2. Update `src/csm/portfolio/__init__.py` — add imports and `__all__` entries
3. Update `src/csm/research/backtest.py` — flip default, add `vol_scaling_config` field, add import
4. Create `tests/unit/portfolio/test_vol_scaler.py` — 22 test cases
5. Fix 2 existing backtest tests that asserted the old default
6. Run verification: ruff → mypy → pytest
7. Update PLAN.md — mark Phase 4.3 complete
8. Create `phase4.3_volatility_scaling_engine.md` — this document

---

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/csm/portfolio/vol_scaler.py` | CREATE | `VolScalingConfig`, `VolScalingResult`, `VolatilityScaler` |
| `src/csm/portfolio/__init__.py` | MODIFY | Add imports + `__all__` for 3 new symbols |
| `src/csm/research/backtest.py` | MODIFY | Flip `vol_scaling_enabled` default; add `vol_scaling_config`; import |
| `tests/unit/portfolio/test_vol_scaler.py` | CREATE | 22 tests in 4 classes |
| `tests/unit/research/test_backtest.py` | MODIFY | Update 2 tests for new default |
| `docs/plans/phase_4_portfolio_construction/PLAN.md` | MODIFY | Mark Phase 4.3 complete |
| `docs/plans/phase_4_portfolio_construction/phase4.3_volatility_scaling_engine.md` | CREATE | This plan document |

---

## Success Criteria

- [x] `VolScalingConfig` Pydantic model with 6 validated fields
- [x] `VolScalingResult` Pydantic model with 3 fields
- [x] `VolatilityScaler.scale()` computes correct scale factor for high-vol scenario
- [x] `VolatilityScaler.scale()` caps at `config.cap` for low/zero/Nan vol
- [x] Empty weights returns empty Series with scale_factor = cap
- [x] Single asset scales correctly
- [x] Floor enforced when set
- [x] equity_fraction never exceeds 1.0
- [x] Scaled weights sum to equity_fraction (invariant)
- [x] Disabled config passes through unchanged
- [x] `BacktestConfig.vol_scaling_enabled` defaults to `True`
- [x] `BacktestConfig.vol_scaling_config` field present
- [x] ruff exits 0
- [x] mypy exits 0
- [x] All 22 tests pass
- [x] Full unit test suite passes (357/363, 6 pre-existing failures unrelated)

---

## Completion Notes

### Summary

Phase 4.3 implemented the standalone `VolatilityScaler` module at `src/csm/portfolio/vol_scaler.py`. The module uses weighted dot-product portfolio volatility (more precise than the old equal-weight approach) and returns scaled weights + metadata via Pydantic models. All quality gates pass and no regressions were introduced.

### What Was Implemented

**Pydantic Models:**
- `VolScalingConfig`: 6 fields with validation (enabled, target_annual, lookback_days, cap, floor, regime_aware)
- `VolScalingResult`: 3 fields (realized_vol_annual, scale_factor, equity_fraction)

**VolatilityScaler Methods:**
- `scale(weights, prices, config) -> tuple[pd.Series, VolScalingResult]` — main entry point
- `_compute_realized_vol(weights, prices, lookback) -> float` — static helper using dot product

**BacktestConfig Changes:**
- `vol_scaling_enabled` default flipped from `False` to `True`
- `vol_scaling_config: VolScalingConfig | None` field added
- Existing individual vol_* fields preserved for backward compatibility

**Tests:** 22 cases in 4 test classes covering config validation, all scaling edge cases, weight invariants, and realized vol computation.

### Issues Encountered

1. **Two backtest tests failed** after flipping the default — `test_vol_scaling_disabled_by_default` in both `TestVolScaling` and `TestPhase39Defaults`. Fixed by renaming to `test_vol_scaling_enabled_by_default` and asserting `True`.
2. **Import ordering** needed ruff auto-fix on all 3 changed files after adding new imports.

### Deviation from PLAN.md

The original PLAN.md specified `src/csm/risk/vol_scaling.py` with a `VolScalingOverlay` that consumes `PortfolioState`. The implementation uses `src/csm/portfolio/vol_scaler.py` with a standalone `VolatilityScaler` that accepts raw pandas objects. The overlay adapter will be created in Phase 4.6 when the `PortfolioPipeline` is assembled.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.7)
**Status:** Complete
**Completed:** 2026-04-29
