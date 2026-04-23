# Phase 1: Core Normalization — Exchange-Aware Inputs Only

**Feature:** Symbol Normalization Layer — Phase 1: Core Normalization
**Branch:** `feature/symbol-normalization-layer`
**Created:** 2026-04-07
**Status:** Complete
**Completed:** 2026-04-07
**Depends On:** Phase 0 (Complete)

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Normalization Rules](#normalization-rules)
6. [Implementation Steps](#implementation-steps)
7. [File Changes](#file-changes)
8. [Success Criteria](#success-criteria)
9. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 1 implements the core normalization logic for `tvkit.symbols`. It handles all symbol variants
that already carry explicit exchange information and converts them to the canonical
`EXCHANGE:SYMBOL` form (uppercase, colon-separated). No network I/O is required — this is a
pure-string transformation layer.

### Parent Plan Reference

- `docs/plans/symbol_normalization_layer/PLAN.md`

### Key Deliverables

1. **`tvkit/symbols/exceptions.py`** — `SymbolNormalizationError` with `original` and `reason` attributes
2. **`tvkit/symbols/models.py`** — `NormalizationType` enum, `NormalizedSymbol`, `NormalizationConfig`
3. **`tvkit/symbols/normalizer.py`** — `normalize_symbol()`, `normalize_symbols()`, `normalize_symbol_detailed()`
4. **`tvkit/symbols/__init__.py`** — Public re-exports
5. **`tests/test_symbols_normalizer.py`** — Full test suite (100% line + branch coverage)
6. **`docs/reference/symbols/normalizer.md`** — API reference

---

## AI Prompt

The following prompt was used to generate this phase:

```
🎯 Objective
Implement Phase 0: Planning & Scaffolding and Phase 1: Core Normalization — Exchange-Aware Inputs Only
for the symbol normalization layer in the tvkit project, following the detailed plan in
`docs/plans/symbol_normalization_layer/PLAN.md`. The process must include creating a phase plan
markdown file, scaffolding the module, implementing the normalization logic, and updating
documentation with progress notes.

📋 Context
- The tvkit project is a type-safe, async-first Python library for TradingView APIs.
- A new symbol normalization layer (`tvkit.symbols`) is being introduced to ensure all symbol
  references are canonical (`EXCHANGE:SYMBOL`, uppercase, colon-separated).
- The implementation is divided into phases. This task covers:
  - Phase 0: Planning & Scaffolding (create module skeleton, planning doc)
  - Phase 1: Core Normalization (implement normalization logic for exchange-aware symbols only,
    no bare tickers or crypto pairs)
- All requirements, API design, error handling, and test strategy are specified in
  `docs/plans/symbol_normalization_layer/PLAN.md`.
- The user requests that the plan for this job be written as a markdown file at
  `docs/plans/symbol_normalization_layer/{phase_name_of_phase}.md`, including the prompt used.
- After implementation, update the main plan with progress notes and commit all changes.

🔧 Requirements
- Read and understand `docs/plans/symbol_normalization_layer/PLAN.md`, focusing on Phase 0 and Phase 1.
- For Phase 0:
  - Create the `tvkit/symbols/` package with empty `__init__.py`, `normalizer.py`, `models.py`,
    `exceptions.py`.
  - Add a planning markdown file for this phase at
    `docs/plans/symbol_normalization_layer/phase0-planning-scaffolding.md`, including the prompt.
- For Phase 1:
  - Implement normalization logic in `tvkit/symbols/normalizer.py` as specified (strip whitespace,
    uppercase, dash-to-colon, validate format).
  - Implement Pydantic models in `tvkit/symbols/models.py` (`NormalizedSymbol`, `NormalizationConfig`,
    `NormalizationType`).
  - Implement `SymbolNormalizationError` in `tvkit/symbols/exceptions.py`.
  - Expose public API in `tvkit/symbols/__init__.py`.
  - Write a test suite at `tests/test_symbols_normalizer.py` covering all cases in the plan.
  - Write API reference at `docs/reference/symbols/normalizer.md`.
- After implementation, update `docs/plans/symbol_normalization_layer/PLAN.md` and the phase plan
  markdown with progress notes (date, issues, etc.).
- Commit all changes as a single commit.
```

---

## Scope

### In Scope (Phase 1)

| Component | Description | Status |
|---|---|---|
| `SymbolNormalizationError` | Exception with `original` + `reason` attributes | Complete |
| `NormalizationType` enum | Primary transformation classification (see Design Decisions §2) | Complete |
| `NormalizedSymbol` model | Frozen Pydantic model with metadata fields | Complete |
| `NormalizationConfig` model | Plain `BaseModel`, temporary deviation (see Design Decisions §4) | Complete |
| `normalize_symbol()` | Single-symbol normalizer, returns `str` | Complete |
| `normalize_symbols()` | 1:1 batch normalizer, preserves order, raises on first error | Complete |
| `normalize_symbol_detailed()` | Returns `NormalizedSymbol` with metadata | Complete |
| Public re-exports in `__init__.py` | All seven public symbols | Complete |
| Test suite | 100% line + branch coverage | Complete |
| API reference | `docs/reference/symbols/normalizer.md` | Complete |

### Out of Scope (Phase 1)

- Bare-ticker resolution via `default_exchange` config (Phase 2)
- Env var support via `pydantic-settings` (Phase 2)
- Crypto slash-pair normalization (Phase 2)
- Integration with `ohlcv.py` call sites (Phase 3)
- Deprecation of `convert_symbol_format` (Phase 3)

---

## Design Decisions

### 1. Broadened validation regex

The master plan specified `^[A-Z0-9]+:[A-Z0-9]+$`. This was determined to be too strict upon
review of existing tvkit symbol usage, which includes:

- `FX_IDC:EURUSD` — underscore in exchange name (already used in `tvkit/quickstart.py`)
- `CME_MINI:ES1!` — underscore in exchange, exclamation in continuous-futures ticker
- `NYSE:BRK.B` — dot in ticker

**Phase 1 validation regex:** `^[A-Z0-9_]+:[A-Z0-9._!]+$`

| Component | Allowed characters | Rationale |
|---|---|---|
| Exchange | `[A-Z0-9_]` | Underscores in exchange families: `FX_IDC`, `CME_MINI`, `CME_MICRO` |
| Ticker | `[A-Z0-9._!]` | Dots: `BRK.B`; exclamation: `ES1!`, `NQ1!` (continuous futures) |

Characters beyond this set (e.g., `/`, `@`, `#`, spaces) are rejected with
`SymbolNormalizationError` and must be resolved before passing to this module.

### 2. `NormalizationType` represents the primary transformation

When multiple transformations are applied (e.g., `"  nasdaq-aapl  "` requires strip + uppercase
+ dash-to-colon), only the **primary transformation** — the most significant one — is recorded.

Precedence (highest to lowest):

| Priority | Type | When assigned |
|---|---|---|
| 1 | `WHITESPACE_STRIP` | Input had leading or trailing whitespace |
| 2 | `DASH_TO_COLON` | Dash was replaced with colon (after strip) |
| 3 | `UPPERCASE_ONLY` | Only case-folding was needed |
| 4 | `ALREADY_CANONICAL` | Input was already in exact canonical form |

This field is **not** a bitmask of every transformation applied. If richer audit information is
needed, use the `original` field and compare against `canonical`. A multi-flag approach is deferred
to a future phase.

### 3. `normalize_symbol` returns `str`, not `NormalizedSymbol`

Ergonomics. The vast majority of call sites just need the canonical string. `normalize_symbol_detailed`
exists for the rare cases where metadata (normalization type, original input) is needed.

### 4. `NormalizationConfig` uses plain `BaseModel` — temporary architectural deviation

**Deviation from standard:** The CLAUDE.md rule "ALL configuration must use Pydantic Settings"
applies to production configuration. `NormalizationConfig` in Phase 1 is a **plain `BaseModel`**
because `pydantic-settings` is not currently declared in `pyproject.toml`.

**This is a deliberate, time-limited exception:**

- Phase 1 ships `NormalizationConfig(BaseModel)` with `default_exchange=None`
- Phase 2 upgrades to `NormalizationConfig(BaseSettings)` with `env_prefix="TVKIT_"` when
  `pydantic-settings` is added as a dependency
- The public API surface (`NormalizationConfig` name and field names) remains unchanged in Phase 2
- No user-facing migration is required for the BaseModel → BaseSettings upgrade

### 5. `normalize_symbols` raises on first invalid input

The function is 1:1 — it does not skip or replace invalid inputs. Raising on the first error is
consistent with fail-fast philosophy and prevents silent data corruption in batch pipelines.

### 6. Zero imports from `tvkit.api`

`tvkit.symbols` is a leaf module. It must not import from any other tvkit sub-package to avoid
circular imports.

---

## Normalization Rules

Applied in order:

| Step | Rule | Config flag |
|---|---|---|
| 1 | Strip leading/trailing whitespace | `strip_whitespace=True` (default) |
| 2 | Raise `SymbolNormalizationError("symbol must not be empty")` if empty after strip | — |
| 3 | Uppercase entire string | — |
| 4 | If no `:` and exactly one `-`: replace first `-` with `:` | — |
| 5 | Validate against `^[A-Z0-9_]+:[A-Z0-9._!]+$` — raise on mismatch | — |
| 6 | Return canonical string | — |

### Input → Output mapping

| Input | Rule Applied | Output |
|---|---|---|
| `"NASDAQ:AAPL"` | None (already canonical) | `"NASDAQ:AAPL"` |
| `"nasdaq:aapl"` | Uppercase | `"NASDAQ:AAPL"` |
| `"NASDAQ-AAPL"` | Dash → colon | `"NASDAQ:AAPL"` |
| `"nasdaq-aapl"` | Uppercase + dash → colon | `"NASDAQ:AAPL"` |
| `"  NASDAQ:AAPL  "` | Strip whitespace | `"NASDAQ:AAPL"` |
| `"  nasdaq-aapl  "` | Strip + uppercase + dash → colon | `"NASDAQ:AAPL"` |
| `"FX_IDC:eurusd"` | Uppercase | `"FX_IDC:EURUSD"` |
| `"NYSE:BRK.B"` | None (already canonical) | `"NYSE:BRK.B"` |
| `"BINANCE:BTCUSDT"` | None | `"BINANCE:BTCUSDT"` |
| `"AAPL"` | No exchange prefix | `SymbolNormalizationError` |
| `""` | Empty | `SymbolNormalizationError` |
| `"INVALID SYMBOL"` | Internal whitespace | `SymbolNormalizationError` |
| `"A:B:C"` | Multiple colons | `SymbolNormalizationError` |
| `"NASDAQ:AAPL:EXTRA"` | Multiple colons | `SymbolNormalizationError` |
| `":AAPL"` | Empty exchange component | `SymbolNormalizationError` |
| `"NASDAQ:"` | Empty ticker component | `SymbolNormalizationError` |

---

## Implementation Steps

### Step 1: `exceptions.py`

Implemented `SymbolNormalizationError(ValueError)` with `original` and `reason` attributes and a
formatted message `f"Cannot normalize '{original}': {reason}"`.

### Step 2: `models.py`

Implemented:
- `NormalizationType(str, Enum)` — five variants including `DEFAULT_EXCHANGE` placeholder for Phase 2
- `NormalizedSymbol(BaseModel)` — frozen, with `canonical`, `exchange`, `ticker`, `original`,
  `normalization_type` fields
- `NormalizationConfig(BaseModel)` — frozen, with `default_exchange: str | None = None` and
  `strip_whitespace: bool = True`

### Step 3: `normalizer.py`

Implemented three public functions:
- `normalize_symbol(symbol, config=None) -> str`
- `normalize_symbols(symbols, config=None) -> list[str]`
- `normalize_symbol_detailed(symbol, config=None) -> NormalizedSymbol`

Internal helper `_normalize_core` contains the shared logic and returns
`tuple[str, NormalizationType]`.

### Step 4: `__init__.py`

Re-exported all seven public symbols:
`normalize_symbol`, `normalize_symbols`, `normalize_symbol_detailed`, `NormalizedSymbol`,
`NormalizationConfig`, `NormalizationType`, `SymbolNormalizationError`

### Step 5: Test suite

Wrote `tests/test_symbols_normalizer.py` with:
- Parametrized happy-path tests (all Phase 1 normalization variants)
- Edge cases (single-char ticker, numeric ticker, long exchange, `FX_IDC:*`, `NYSE:BRK.B`,
  lowercase + whitespace + dash combined, duplicate inputs in `normalize_symbols`)
- All error conditions from the plan
- `normalize_symbols` batch tests (order preservation, 1:1 no dedup, raises on first invalid)
- Detailed model tests (`NormalizationType` for each variant, field assertions)

### Step 6: API reference

Wrote `docs/reference/symbols/normalizer.md`.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `tvkit/symbols/exceptions.py` | MODIFY | Implement `SymbolNormalizationError` |
| `tvkit/symbols/models.py` | MODIFY | Implement `NormalizationType`, `NormalizedSymbol`, `NormalizationConfig` |
| `tvkit/symbols/normalizer.py` | MODIFY | Implement normalization functions |
| `tvkit/symbols/__init__.py` | MODIFY | Public re-exports |
| `tests/test_symbols_normalizer.py` | CREATE | Full test suite |
| `docs/reference/symbols/normalizer.md` | CREATE | API reference |
| `docs/plans/symbol_normalization_layer/phase1-core-normalization.md` | CREATE | This plan document |
| `docs/plans/symbol_normalization_layer/PLAN.md` | MODIFY | Phase 0 + Phase 1 completion notes |

---

## Success Criteria

- [x] `normalize_symbol("nasdaq:aapl")` → `"NASDAQ:AAPL"`
- [x] `normalize_symbol("NASDAQ-AAPL")` → `"NASDAQ:AAPL"`
- [x] `normalize_symbol("  NASDAQ:AAPL  ")` → `"NASDAQ:AAPL"`
- [x] `normalize_symbol("FX_IDC:eurusd")` → `"FX_IDC:EURUSD"`
- [x] `normalize_symbol("NYSE:BRK.B")` → `"NYSE:BRK.B"`
- [x] `normalize_symbol("AAPL")` raises `SymbolNormalizationError`
- [x] `normalize_symbols` is 1:1 (duplicate inputs → duplicate outputs)
- [x] `normalize_symbol_detailed` returns correct primary `NormalizationType`
- [x] 100% test coverage for `tvkit/symbols/`
- [x] `uv run mypy tvkit/symbols/` exits 0
- [x] `uv run ruff check tvkit/symbols/` exits 0
- [x] API reference complete at `docs/reference/symbols/normalizer.md`

---

## Completion Notes

### Summary

Phase 1 complete. All normalization logic, Pydantic models, exception class, public API, test suite,
and API reference docs were implemented in a single session. The validation regex was broadened from
the original plan's `^[A-Z0-9]+:[A-Z0-9]+$` to `^[A-Z0-9_]+:[A-Z0-9._!]+$` after review of
existing symbol usage in the codebase. Quality gates (ruff, mypy, pytest) all pass.

### Issues Encountered

1. **Validation regex too strict** — The master plan specified `^[A-Z0-9]+:[A-Z0-9]+$`, which would
   reject `FX_IDC:EURUSD` (already used in `tvkit/quickstart.py`) and `NYSE:BRK.B`. Broadened to
   `^[A-Z0-9_]+:[A-Z0-9._!]+$`. The master plan was not updated as this is a Phase 1 implementation
   detail, but the PLAN.md notes section records this decision.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Sonnet 4.6)
**Status:** Complete
**Completed:** 2026-04-07
