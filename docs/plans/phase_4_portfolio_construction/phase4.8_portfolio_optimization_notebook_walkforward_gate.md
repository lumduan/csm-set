# Phase 4.8 — Portfolio Optimization Notebook & Walk-Forward Gate

**Feature:** Portfolio Optimization Notebook & Walk-Forward Gate for the SET Cross-Sectional Momentum Strategy
**Branch:** `feature/phase-4-portfolio-construction`
**Created:** 2026-04-29
**Status:** Complete
**Completed:** 2026-04-29
**Depends On:** Phase 4.7 (Execution Simulation & Trade List — complete)

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

Phase 4.8 is the final sub-phase of the Portfolio Construction & Risk Management layer. It delivers three artefacts that serve as the Phase 4 exit gate:

1. **Walk-Forward Gate overlay** (`src/csm/portfolio/walkforward_gate.py`) — a stateless validation utility that gates walk-forward backtest results against configurable pass/fail criteria. Accepts generic `dict[str, Any]` fold metrics (not `WalkForwardResult`) to keep `csm.portfolio` free of upward dependencies on `csm.research`.

2. **Portfolio Optimization Notebook** (`notebooks/04_portfolio_optimization.ipynb`) — a 9-section interactive notebook with Thai markdown that exercises every Phase 4 overlay, compares weighting schemes, sweeps parameters, stress-tests the circuit breaker, runs walk-forward validation, and prints PASS/FAIL for all 13 success criteria from PLAN.md.

3. **CI Gate Specification** (`docs/plans/phase_4_portfolio_construction/walk_forward_ci_gate.md`) — defines the `pytest -m walk_forward` marker, pass/fail thresholds, and CI integration strategy for Phase 5/8.

### Parent Plan Reference

- `docs/plans/phase_4_portfolio_construction/PLAN.md`

### Key Deliverables

1. **`WalkForwardGateConfig`, `FoldGateResult`, `WalkForwardGateResult`, `WalkForwardGate`** — validation gate with `validate()` method
2. **`WalkForwardGate` unit tests** — 25 tests covering config validation, result models, and validation logic
3. **Portfolio Optimization Notebook** — 9 sections with Thai markdown, exercising all Phase 4 overlays
4. **CI Gate Spec** — pytest marker definition, thresholds, integration strategy
5. **Plan document** — this file
6. **PLAN.md update** — Phase 4.8 completion notes

---

## AI Prompt

The following prompt was used to generate this phase:

```
🎯 Objective
Design and implement Phase 4.8 — Portfolio Optimization Notebook & Walk-Forward
Gate for the SET Cross-Sectional Momentum Strategy, following all architectural,
type safety, and documentation standards. Deliver a detailed implementation plan
as a markdown file, then implement the notebook and walk-forward gate,
comprehensive tests, and update all relevant documentation and progress tracking
files.

📋 Context
- The project is a production-grade, type-safe, async-first Python library for
  SET momentum strategies.
- Phase 4.8 focuses on building a Portfolio Optimization Notebook and a
  Walk-Forward Gate overlay that enables interactive portfolio optimization,
  walk-forward validation, and robust gating of pipeline results.
- The previous phase (4.7) delivered the Execution Simulation & Trade List
  overlay, with detailed planning and documentation standards.
- Documentation and progress tracking are maintained in markdown files under
  docs/plans/phase_4_portfolio_construction/.
- All code must use explicit type annotations, Pydantic models for configs/
  results, and comprehensive tests.
- Reference docs/plans/phase_4_portfolio_construction/PLAN.md (focus on Phase
  4.8) and docs/plans/phase_4_portfolio_construction/phase4.7_execution_
  simulation_trade_list.md for context and standards.

🔧 Requirements
- Carefully read and understand:
  - docs/plans/phase_4_portfolio_construction/PLAN.md (focus on Phase 4.8)
  - docs/plans/phase_4_portfolio_construction/phase4.7_execution_simulation_
    trade_list.md (for last implementation and standards)
- Before coding, create a detailed implementation plan for Phase 4.8 as
  docs/plans/phase_4_portfolio_construction/phase4.8_portfolio_optimization_
  notebook_walkforward_gate.md, including the full prompt used (as in phase4.7).
- The plan must follow the format in docs/plans/examples/phase1-sample.md,
  including Table of Contents, Scope, Design Decisions, Implementation Steps,
  File Changes, Success Criteria, and Completion Notes.
- Implement the Portfolio Optimization Notebook and Walk-Forward Gate overlay:
  - The notebook should enable interactive portfolio optimization, visualization,
    and diagnostics for walk-forward analysis.
  - The Walk-Forward Gate overlay should enforce robust validation and gating of
    pipeline results, with clear error handling and reporting.
  - Use explicit type annotations and Pydantic validation throughout.
- Write ≥10 unit tests in tests/unit/portfolio/test_walkforward_gate.py (or
  similar).
- Update PLAN.md and phase4.8_portfolio_optimization_notebook_walkforward_
  gate.md with progress notes, completion status, and any issues encountered.
- Ensure all code passes ruff, mypy, and pytest gates.
- Commit all changes with a clear, standards-compliant message.
```

---

## Scope

### In Scope

| Component | Description | Status |
|-----------|-------------|--------|
| `src/csm/portfolio/walkforward_gate.py` | WalkForwardGate, config, result models | Complete |
| `src/csm/portfolio/__init__.py` | Add WalkForwardGate exports | Complete |
| `tests/unit/portfolio/test_walkforward_gate.py` | 25 unit tests in 5 classes | Complete |
| `docs/plans/phase_4_portfolio_construction/walk_forward_ci_gate.md` | CI gate specification | Complete |
| `notebooks/04_portfolio_optimization.ipynb` | 9-section portfolio optimization notebook | Complete |
| Plan document | phase4.8_portfolio_optimization_notebook_walkforward_gate.md | Complete |
| PLAN.md update | Phase 4.8 status → Complete | Complete |

### Out of Scope

- `pytest -m walk_forward` marker registration in `pyproject.toml` (deferred to Phase 8 CI integration)
- GitHub Actions workflow implementing the CI gate (deferred to Phase 8)
- Pipeline assembly wiring overlays into `MomentumBacktest.run()` (deferred to future pipeline phase)
- `BacktestResult.trade_lists` extension (deferred to future pipeline phase)

---

## Design Decisions

### 1. WalkForwardGate: generic `dict[str, Any]` input, not `WalkForwardResult` dependency

The gate accepts `list[dict[str, Any]]` for fold metrics and `dict[str, float]` for aggregate metrics rather than importing `WalkForwardResult` from `csm.research.walk_forward`. This keeps `csm.portfolio` free of upward dependencies on `csm.research`, consistent with the PLAN.md dependency graph.

**Rationale:** The notebook extracts metrics from `WalkForwardResult` objects and passes them to the gate as plain dicts. This is a thin adapter (~3 lines of dict construction per fold). The gate is a pure validation utility with no domain knowledge of the backtest infrastructure.

### 2. `validate()` method name instead of `apply()`

The method is named `validate()` rather than `apply()` because the gate operates on backtest results, not portfolio weights. All other overlays use `apply()` or `scale()` because they transform weight vectors.

**Rationale:** The semantic distinction makes the API self-documenting. A gate that produces PASS/FAIL verdicts on walk-forward results is fundamentally different from an overlay that scales portfolio weights.

### 3. Stateless class following Phase 4 pattern

The `WalkForwardGate` class is stateless — all relevant state is passed via the `validate()` method parameters. Config defaults are used when `config=None`.

**Rationale:** Consistent with all Phase 4 standalone overlays (VolatilityScaler, LiquidityOverlay, DrawdownCircuitBreaker, SectorRegimeConstraintEngine, ExecutionSimulator). Makes the gate trivially testable and parallel-safe.

### 4. CI gate spec: standalone markdown, marker registration deferred to Phase 8

The `walk_forward_ci_gate.md` documents the intended CI integration (pytest marker `walk_forward`, pass/fail thresholds, GitHub Actions workflow sketch). The actual `pytest -m walk_forward` marker registration in `pyproject.toml` is deferred to Phase 8 per PLAN.md "Future Enhancements" §611.

**Rationale:** Phase 4.8 defines the spec and builds the validation logic. Phase 8 integrates the marker into CI, adds the GitHub Actions workflow, and connects the gate to automated PR checks. This separation keeps Phase 4 focused on portfolio construction.

### 5. Notebook: synthetic data for reproducible results

Sections 4 (circuit breaker stress test), 5 (capacity sweep), 7 (walk-forward), and 9 (Monte Carlo) use deterministic synthetic data with `np.random.default_rng(42)` to ensure reproducible PASS/FAIL results across environments. Sections 1–3 use ParquetStore data when available; fall back to synthetic data if the store is empty.

**Rationale:** The notebook is the Phase 4 exit gate — its PASS/FAIL verdict must be deterministic and reproducible. Real data varies by environment; synthetic data guarantees the same result every time.

### 6. Notebook: Thai markdown convention

All markdown cells use Thai language per project convention (documented in memory: `feedback_notebook_thai.md`). Section headings follow the `## ส่วนที่ N: <Thai title>` pattern established in notebooks 01–03.

---

## Implementation Steps

1. Create `src/csm/portfolio/walkforward_gate.py` — WalkForwardGate, config, result models
2. Update `src/csm/portfolio/__init__.py` — add 4 new exports
3. Create `tests/unit/portfolio/test_walkforward_gate.py` — 25 tests in 5 classes
4. Run ruff → mypy → pytest (25 new + full suite regression)
5. Create `docs/plans/phase_4_portfolio_construction/phase4.8_portfolio_optimization_notebook_walkforward_gate.md` — this document
6. Create `docs/plans/phase_4_portfolio_construction/walk_forward_ci_gate.md` — CI gate spec
7. Fill `notebooks/04_portfolio_optimization.ipynb` — 9 sections
8. Update PLAN.md — mark Phase 4.8 complete
9. Commit all changes

---

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/csm/portfolio/walkforward_gate.py` | CREATE | WalkForwardGate, WalkForwardGateConfig, WalkForwardGateResult, FoldGateResult |
| `src/csm/portfolio/__init__.py` | MODIFY | Add 4 new exports |
| `tests/unit/portfolio/test_walkforward_gate.py` | CREATE | 25 tests in 5 classes |
| `docs/plans/phase_4_portfolio_construction/phase4.8_portfolio_optimization_notebook_walkforward_gate.md` | CREATE | This plan document |
| `docs/plans/phase_4_portfolio_construction/walk_forward_ci_gate.md` | CREATE | CI gate specification |
| `notebooks/04_portfolio_optimization.ipynb` | MODIFY | Fill 9-section notebook |
| `docs/plans/phase_4_portfolio_construction/PLAN.md` | MODIFY | Mark Phase 4.8 complete |

---

## Success Criteria

- [x] `WalkForwardGate` with `WalkForwardGateConfig`, `FoldGateResult`, `WalkForwardGateResult`
- [x] `WalkForwardGate.validate()` accepts generic fold metrics dicts and returns pass/fail verdict
- [x] Config validation via Pydantic with cross-field validator
- [x] Disabled pass-through (config.enabled=False → always passed=True)
- [x] Per-fold OOS Sharpe threshold check
- [x] IS/OOS Sharpe ratio ceiling check (overfitting detection)
- [x] Minimum folds required check
- [x] Human-readable failure messages
- [x] Deterministic (same input → same output)
- [x] 25 unit tests in `tests/unit/portfolio/test_walkforward_gate.py` all passing
- [x] ruff exits 0 on all new and modified files
- [x] mypy exits 0 on `src/csm/portfolio/walkforward_gate.py`
- [x] `04_portfolio_optimization.ipynb` with 9 sections, Thai markdown
- [x] `walk_forward_ci_gate.md` complete with pytest marker spec and CI integration strategy
- [x] PLAN.md updated with Phase 4.8 completion notes
- [x] Full unit test suite passes with no regressions

---

## Completion Notes

### Summary

Phase 4.8 implemented the Walk-Forward Gate overlay, portfolio optimization notebook, and CI gate specification — the final sub-phase of Phase 4 Portfolio Construction & Risk Management.

The WalkForwardGate is a stateless validation utility at `src/csm/portfolio/walkforward_gate.py` that gates walk-forward backtest results against configurable pass/fail criteria. It accepts generic `dict[str, Any]` fold metrics (not `WalkForwardResult` directly) to keep `csm.portfolio` free of upward dependencies on `csm.research`. The gate checks three criteria: per-fold OOS Sharpe minimum, IS/OOS Sharpe ratio ceiling (overfitting detection), and minimum number of passing folds. It produces a `WalkForwardGateResult` with a boolean `passed` verdict, per-fold details, and a human-readable `failures` list.

The portfolio optimization notebook (`notebooks/04_portfolio_optimization.ipynb`) contains 9 sections with Thai markdown: setup and baseline, weighting scheme comparison, vol scaling sensitivity, circuit breaker stress test, capacity sweep, sector/turnover analysis, walk-forward OOS validation, sign-off with all 13 success criteria, and Monte Carlo robustness checks (random-weight allocation and path-dependency bootstrap).

### What Was Implemented

**WalkForwardGate (walkforward_gate.py):**
- `WalkForwardGateConfig` (5 fields): `enabled`, `min_oos_sharpe`, `max_is_oos_sharpe_ratio`, `require_all_folds_positive_sharpe`, `min_folds_required` — with cross-field validator
- `FoldGateResult` (10 fields): per-fold pass/fail with optional date range fields
- `WalkForwardGateResult` (8 fields): aggregate pass/fail with `failures` list
- `WalkForwardGate.validate(fold_metrics, aggregate_oos_metrics, is_metrics, config) -> WalkForwardGateResult`

**Tests:** 25 cases across 5 test classes:
- `TestWalkForwardGateConfig` (5 tests): defaults, custom values, boundary validation errors
- `TestWalkForwardGateResult` (3 tests): passed/failed/default construction
- `TestFoldGateResult` (3 tests): passing fold, failing fold, optional date fields
- `TestWalkForwardGate` (14 tests): disabled pass-through, all-pass, mixed-fail, all-fail, insufficient folds, empty fold list, single fold, IS/OOS ratio exceeded, is_metrics=None skip, missing optional keys, missing sharpe key, determinism, default config, require_all_folds=False

**Portfolio Optimization Notebook:** 9 sections covering all 13 PLAN.md success criteria.

**CI Gate Spec:** pytest marker definition, pass/fail thresholds, GitHub Actions workflow sketch, Phase 8 integration strategy.

### Issues Encountered

1. **Mypy `object` → `float`/`int` conversion errors** — `dict[str, object]` values cannot be passed to `float()` or `int()` directly. Changed parameter type to `dict[str, Any]` which is compatible with all types and better represents the "we accept arbitrary dicts from external sources" semantics.

2. **Ruff I001 import sorting** — `from typing import Self` was placed after the `pydantic` import instead of before it (third-party imports go after stdlib). Reordered.

3. **`test_require_all_folds_false_allows_mixed` initial failure** — Setting `require_all_folds_positive_sharpe=False` alone doesn't allow a negative-OOS-Sharpe fold to pass because `min_oos_sharpe=0.0` (default) is still enforced per-fold. Fixed by also setting `min_oos_sharpe=-0.30` in the test config.

### Deviation from PLAN.md

The PLAN.md specified the CI gate spec path as `docs/plans/phase4_portfolio_construction/walk_forward_ci_gate.md`. The implementation uses `docs/plans/phase_4_portfolio_construction/walk_forward_ci_gate.md` (underscore in `phase_4`) for consistency with all other phase plan documents in the same directory.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.7)
**Status:** Complete
**Completed:** 2026-04-29
