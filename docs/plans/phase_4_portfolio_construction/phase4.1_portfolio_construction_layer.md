# Phase 4.1 — Portfolio Construction Layer

**Feature:** First-class `PortfolioConstructor` API replacing inline `_select_holdings()`
**Branch:** `feature/phase-4-portfolio-construction`
**Created:** 2026-04-29
**Status:** Complete
**Completed:** 2026-04-29
**Depends On:** Phase 3.9 (Backtesting — complete)

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

Phase 4.1 promotes Phase 3.9's inline `MomentumBacktest._select_holdings()` and `_apply_buffer_logic()` into a first-class `PortfolioConstructor` API with no semantic change. It also creates the foundational Pydantic state models (`PortfolioState`, `OverlayContext`, `OverlayJournalEntry`) that the entire Phase 4 overlay pipeline depends on.

### Parent Plan Reference

- `docs/plans/phase_4_portfolio_construction/PLAN.md`

### Key Deliverables

1. **`src/csm/portfolio/state.py`** — `PortfolioState`, `OverlayContext`, `OverlayJournalEntry`, `CircuitBreakerState` Pydantic models
2. **`src/csm/portfolio/construction.py`** — Rewritten `PortfolioConstructor` with full Phase 3.9 selection + buffer logic
3. **`src/csm/portfolio/exceptions.py`** — `SelectionError` exception
4. **`src/csm/portfolio/__init__.py`** — Updated public exports
5. **`src/csm/research/backtest.py`** — `MomentumBacktest` delegates to `PortfolioConstructor`
6. **`tests/unit/portfolio/test_construction.py`** — Comprehensive test suite (≥ 8 cases)
7. **`tests/unit/portfolio/test_state.py`** — State model validation tests
8. **`tests/unit/research/test_backtest_phase4_parity.py`** — Snapshot parity test (1e-9 tolerance)

---

## AI Prompt

The following prompt was used to generate this phase:

```
🎯 Objective
Design and implement Phase 4.1 — Portfolio Construction Layer as outlined in the Phase 4 master plan.
Promote Phase 3.9's inline MomentumBacktest._select_holdings() into a first-class PortfolioConstructor
API with no semantic change, and create the foundational Pydantic state models.

📋 Context
- The project is in /Users/sarat/Code/csm-set, branch feature/phase-4-portfolio-construction
- The Phase 4 master plan is at docs/plans/phase_4_portfolio_construction/PLAN.md
- The existing _select_holdings() and _apply_buffer_logic() live as private methods on MomentumBacktest
  in src/csm/research/backtest.py (lines 245-343)
- The existing PortfolioConstructor in src/csm/portfolio/construction.py is a minimal stub with only
  quintile-based selection and a build() method
- No SelectionResult, PortfolioState, OverlayContext, or OverlayJournalEntry models exist yet
- All defaults are in src/csm/config/constants.py

🔧 Requirements
- Create SelectionConfig and SelectionResult Pydantic models
- Rewrite PortfolioConstructor.select() to implement the full Phase 3.9 logic:
  top-quintile composite z-score selection + replacement buffer + exit-rank floor + entry mask support
- Move _apply_buffer_logic() into PortfolioConstructor as a private method
- Create PortfolioState, OverlayContext, OverlayJournalEntry Pydantic models in state.py
- Add SelectionError to exceptions.py
- Update MomentumBacktest to delegate _select_holdings() to PortfolioConstructor
- Write unit tests (≥ 8 cases) covering: empty cross-section, buffer retention, exit floor eviction,
  holdings count band enforcement, entry mask restriction, small universe fallback, determinism
- Create snapshot parity test verifying byte-identical equity curve to Phase 3.9 baseline
- All code must have type annotations, Pydantic validation, comprehensive error handling
- Follow project conventions: uv run for commands, ruff/mypy/pytest gates
```

---

## Scope

### In Scope (Phase 4.1)

| Component | Description | Status |
|---|---|---|
| `SelectionConfig` | Pydantic model: `n_holdings_min`, `n_holdings_max`, `buffer_rank_threshold`, `exit_rank_floor` | Complete |
| `SelectionResult` | Pydantic model: `selected`, `evicted`, `retained`, `ranks` | Complete |
| `PortfolioConstructor.select()` | Full Phase 3.9 logic: composite z-score + buffer + exit floor + entry mask | Complete |
| `PortfolioConstructor._apply_buffer_logic()` | Extracted from `MomentumBacktest` | Complete |
| `PortfolioState` | Pydantic model: `asof`, `target_weights`, `equity_fraction`, `regime`, `breaker_state`, `journal` | Complete |
| `OverlayContext` | Pydantic model: `prices_window`, `volumes_window`, `index_prices_window`, `sector_map`, `equity_curve_to_date` | Complete |
| `OverlayJournalEntry` | Pydantic model: `overlay`, `asof`, `decision`, `inputs`, `outputs` | Complete |
| `CircuitBreakerState` | StrEnum placeholder: `NORMAL` (Phase 4.5 adds `TRIPPED`, `RECOVERING`) | Complete |
| `SelectionError` | Exception raised for invalid selection inputs | Complete |
| `MomentumBacktest` refactor | Delegate `_select_holdings()` to `PortfolioConstructor`; remove `_apply_buffer_logic()` | Complete |
| Unit tests | ≥ 8 cases for `PortfolioConstructor.select()` | Complete |
| State model tests | Validation, serialization, defaults | Complete |
| Snapshot parity test | Phase 3.9 config → byte-identical equity curve (1e-9) | Complete |

### Out of Scope (Phase 4.1)

- Weight optimizer expansion (Phase 4.2)
- Volatility scaling overlay (Phase 4.3)
- Liquidity & capacity overlay (Phase 4.4)
- Drawdown circuit breaker (Phase 4.5)
- Sector cap and regime constraint extraction (Phase 4.6)
- Execution simulation (Phase 4.7)
- The `PortfolioConstructor.build()` method — preserved as-is from existing stub

---

## Design Decisions

### 1. `SelectionConfig` extracts selection fields from `BacktestConfig`

Rather than passing the entire `BacktestConfig` (22+ fields), `PortfolioConstructor.select()` accepts a focused `SelectionConfig` with only the 4 fields it needs. This keeps the constructor decoupled from backtest concerns and makes it independently testable.

```python
class SelectionConfig(BaseModel):
    n_holdings_min: int = Field(default=40, ge=1, le=200)
    n_holdings_max: int = Field(default=60, ge=1, le=200)
    buffer_rank_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    exit_rank_floor: float = Field(default=0.35, ge=0.0, le=1.0)
```

### 2. `SelectionResult` tracks evictions and ranks

The existing code returns a bare `list[str]`. Phase 4.1 returns a `SelectionResult` with:
- `selected`: final symbol list
- `evicted`: symbols removed (by buffer replacement or exit floor)
- `retained`: symbols kept from current holdings
- `ranks`: `dict[str, float]` mapping symbol → percentile rank

This enables the overlay journal to record what happened at the selection step — critical for debugging and stress testing.

### 3. `_apply_buffer_logic()` becomes a private method on `PortfolioConstructor`

The buffer logic is tightly coupled to selection — it operates on the same composite score and percentile ranks. Moving it as a private method keeps the class self-contained. The logic is copied verbatim; the only change is `self` refers to `PortfolioConstructor` instead of `MomentumBacktest`.

### 4. `MomentumBacktest` delegates, doesn't duplicate

`MomentumBacktest._select_holdings()` becomes a thin wrapper that constructs `SelectionConfig` from `BacktestConfig` and delegates to `PortfolioConstructor.select()`. `MomentumBacktest.__init__()` accepts an optional `portfolio_constructor` parameter.

### 5. `CircuitBreakerState` uses a forward-compatible StrEnum

Phase 4.5 will add `TRIPPED` and `RECOVERING` states. Phase 4.1 defines only `NORMAL` to avoid forward-reference issues in `PortfolioState`.

### 6. `PortfolioState` uses `pd.Timestamp` with `arbitrary_types_allowed`

pandas.Timestamp is not natively supported by Pydantic v2's strict mode. We use `model_config = {"arbitrary_types_allowed": True}`, consistent with how `BacktestConfig` handles pandas types elsewhere in the codebase.

### 7. `entry_mask` parameter preserved exactly

The `entry_mask: set[str] | None = None` parameter on `select()` matches the Phase 3.9 signature exactly — restricts new entry candidates while preserving existing holdings' buffer eligibility.

---

## Implementation Steps

### Step 1: Create `src/csm/portfolio/state.py`

Create `PortfolioState`, `OverlayContext`, `OverlayJournalEntry`, and `CircuitBreakerState` Pydantic models:

- `CircuitBreakerState` — StrEnum with `NORMAL` (TRIPPED, RECOVERING in Phase 4.5)
- `OverlayJournalEntry` — `overlay`, `asof`, `decision`, `inputs`, `outputs`
- `PortfolioState` — `asof`, `target_weights`, `equity_fraction`, `regime`, `breaker_state`, `journal`
- `OverlayContext` — `prices_window`, `volumes_window`, `index_prices_window`, `sector_map`, `equity_curve_to_date`

### Step 2: Add `SelectionConfig` and `SelectionResult` to `construction.py`

### Step 3: Rewrite `PortfolioConstructor.select()` with full Phase 3.9 logic

### Step 4: Move `_apply_buffer_logic()` into `PortfolioConstructor` as private method

### Step 5: Add `SelectionError` to `exceptions.py`

### Step 6: Update `__init__.py` with all new exports

### Step 7: Refactor `MomentumBacktest` to delegate to `PortfolioConstructor`

### Step 8: Write unit tests for construction (≥ 8) and state models

### Step 9: Write snapshot parity test

### Step 10: Update PLAN.md with completion notes

### Step 11: Run quality gates (ruff, mypy, pytest)

### Step 12: Commit

---

## File Changes

| File | Action | Description |
|---|---|---|
| `src/csm/portfolio/state.py` | CREATE | `PortfolioState`, `OverlayContext`, `OverlayJournalEntry`, `CircuitBreakerState` |
| `src/csm/portfolio/construction.py` | REWRITE | Full `PortfolioConstructor` with `select()`, `_apply_buffer_logic()`, `build()`; `SelectionConfig`, `SelectionResult` |
| `src/csm/portfolio/exceptions.py` | MODIFY | Add `SelectionError` |
| `src/csm/portfolio/__init__.py` | MODIFY | Add new exports |
| `src/csm/research/backtest.py` | MODIFY | Delegate `_select_holdings()` to `PortfolioConstructor`; remove `_apply_buffer_logic()` |
| `tests/unit/portfolio/test_construction.py` | REWRITE | 11 comprehensive test cases |
| `tests/unit/portfolio/test_state.py` | CREATE | State model validation tests |
| `tests/unit/research/test_backtest_phase4_parity.py` | CREATE | Snapshot parity test |
| `docs/plans/phase_4_portfolio_construction/PLAN.md` | MODIFY | Phase 4.1 completion notes |
| `docs/plans/phase_4_portfolio_construction/phase4.1_portfolio_construction_layer.md` | CREATE | This plan document |

---

## Success Criteria

- [x] `PortfolioConstructor.select()` returns `SelectionResult` with correct selected/evicted/retained symbols
- [x] Buffer logic retains holdings when replacement rank difference < buffer_threshold
- [x] Exit floor evicts holdings unconditionally when rank < exit_rank_floor
- [x] Holdings count enforced: n_holdings_min ≤ len(selected) ≤ n_holdings_max (when universe permits)
- [x] Entry mask restricts new entries but preserves existing holding eligibility
- [x] Small universe fallback: never returns empty when candidates exist
- [x] Deterministic: identical inputs produce identical outputs
- [x] Snapshot parity: Phase 3.9 config produces byte-identical equity curve (1e-9)
- [x] `uv run ruff check .` exits 0
- [x] `uv run mypy src/` exits 0
- [x] `uv run pytest tests/unit/portfolio/ -v` all pass
- [x] `uv run pytest tests/unit/research/test_backtest_phase4_parity.py -v` passes
- [x] Existing backtest tests continue to pass (no regressions)

---

## Completion Notes

### Summary

Phase 4.1 complete. `PortfolioConstructor.select()` now implements the full Phase 3.9 selection logic (composite z-score + buffer + exit floor + entry mask) as a standalone, testable API. The foundational state models (`PortfolioState`, `OverlayContext`, `OverlayJournalEntry`) are in place for the overlay pipeline. `MomentumBacktest` delegates selection to `PortfolioConstructor`, and snapshot parity tests confirm byte-identical output with the Phase 3.9 baseline.

### Issues Encountered

None.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.7)
**Status:** Complete
**Completed:** 2026-04-29
