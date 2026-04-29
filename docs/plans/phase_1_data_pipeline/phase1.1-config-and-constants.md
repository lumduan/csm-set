# Phase 1.1 — Config & Constants

**Feature:** Data Pipeline — Config & Constants Layer
**Branch:** `feature/phase-1-data-pipeline`
**Created:** 2026-04-21
**Status:** Complete
**Completed:** 2026-04-21
**Depends On:** None (foundation layer)

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Gap Analysis](#gap-analysis)
5. [Design Decisions](#design-decisions)
6. [Implementation Steps](#implementation-steps)
7. [Verification Addendum](#verification-addendum)
8. [File Changes](#file-changes)
9. [Success Criteria](#success-criteria)
10. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 1.1 establishes the typed configuration and constants layer that all subsequent sub-phases
depend on. No business logic lives here — only compile-time constants (`constants.py`) and
runtime-injectable settings (`settings.py`). Every downstream component imports from this layer
to stay free of magic numbers and hardcoded paths.

### Parent Plan Reference

- `docs/plans/phase1_data_pipeline/PLAN.md` — Phase 1.1 section

### Key Deliverables

1. **`src/csm/config/constants.py`** — SET-specific compile-time constants (no env vars, no Pydantic)
2. **`src/csm/config/settings.py`** — `Settings(BaseSettings)` with `CSM_` env prefix and singleton `get_settings()`
3. **`tests/unit/config/test_settings.py`** — Unit tests for settings load, `public_mode` defaults, and env override

---

## AI Prompt

The following prompt was used to initiate this implementation phase:

```
🎯 Objective
Create a comprehensive implementation plan and execution workflow for Phase 1.1 ("Config &
Constants") of the Data Pipeline Master Plan, following the specifications in
`docs/plans/phase1_data_pipeline/PLAN.md`. The plan should be documented in a new markdown file,
and the implementation should proceed only after the plan is complete. Upon completion, update the
relevant documentation files with progress notes and commit all changes.

📋 Context
- The project is a data pipeline for SET OHLCV data, with a strong emphasis on type safety,
  async-first architecture, and Pydantic-based configuration.
- The master plan for the data pipeline is detailed in `docs/plans/phase1_data_pipeline/PLAN.md`.
- The deliverables for Phase 1.1 are:
  - `src/csm/config/constants.py` with SET-specific constants (no env vars, no Pydantic)
  - `src/csm/config/settings.py` with a Pydantic `Settings` class, env var binding, and singleton
    accessor
  - Unit tests for settings loading and public_mode logic

🔧 Requirements
- Read and understand the requirements in `docs/plans/phase1_data_pipeline/PLAN.md`, focusing on
  Phase 1.1.
- Draft a detailed implementation plan for Phase 1.1 in markdown, saved as
  `docs/plans/phase1_data_pipeline/phase1.1-config-and-constants.md`. The plan must include:
  - A summary of objectives and deliverables
  - A step-by-step breakdown of tasks
  - Any anticipated challenges or open questions
  - The exact prompt used for this planning phase (for traceability)
- Do not begin coding until the plan is complete and saved.
- After implementation, update both `docs/plans/phase1_data_pipeline/PLAN.md` and
  `docs/plans/phase1_data_pipeline/phase1.1-config-and-constants.md` with progress notes,
  completion dates, and any issues encountered.
- Ensure all code is type-safe, uses Pydantic for settings, and follows the architectural and
  documentation standards of the project.
- Commit all changes with a clear, standards-compliant commit message.
```

---

## Scope

### In Scope (Phase 1.1)

| Component | Description | Status |
|---|---|---|
| `constants.py` — `INDEX_SYMBOL` | Benchmark symbol for tvkit (`"SET:SET"`) | Complete |
| `constants.py` — `SET_SECTOR_CODES` | `dict[str, str]` sector code → name mapping | Complete |
| `constants.py` — `MIN_PRICE_THB` | Universe price floor (1.0 THB) | Complete |
| `constants.py` — `MIN_AVG_DAILY_VOLUME` | Liquidity threshold (1,000,000 THB avg daily) | Complete |
| `constants.py` — `MIN_DATA_COVERAGE` | 80% minimum valid bars in lookback window | Complete |
| `constants.py` — `LOOKBACK_YEARS` | 15-year history depth for full backtest | Complete |
| `constants.py` — `REBALANCE_FREQ` | `"BME"` pandas business month-end offset alias | Complete |
| `settings.py` — `Settings(BaseSettings)` | `CSM_` prefix, `.env` binding, frozen | Complete |
| `settings.py` — `public_mode` | Defaults `False`; blocks data access when `True` | Complete |
| `settings.py` — `results_dir` | Path to git-committed artefacts | Complete |
| `settings.py` — `data_dir` | Path to gitignored data root | Complete |
| `settings.py` — `tvkit_concurrency` | Semaphore limit for `fetch_batch` (`gt=0`) | Complete |
| `settings.py` — `tvkit_retry_attempts` | Retry count for transient errors (`ge=0`) | Complete |
| `settings.py` — `log_level` | Log verbosity | Complete |
| `settings.py` — `get_settings()` | `functools.lru_cache` singleton accessor | Complete |
| `config/__init__.py` | Updated public exports for new names | Complete |
| Call-site updates | `universe.py`, `momentum.py` updated to new constant names | Complete |
| conftest.py | Move API imports inside fixture body to fix collection isolation | Complete |
| `tests/unit/config/test_settings.py` | Three required unit tests for settings | Complete |

### Out of Scope (Phase 1.1)

- Parquet storage layer (`ParquetStore`) — Phase 1.2
- tvkit loader (`OHLCVLoader`) and `DataAccessError` — Phase 1.3
- Universe builder and price cleaner — Phases 1.4–1.5
- Bulk fetch script and notebook — Phases 1.6–1.7
- Additional Jegadeesh-Titman constants (`DEFAULT_LOOKBACK_MONTHS`, `DEFAULT_SKIP_MONTHS`,
  `DEFAULT_TOP_QUANTILE`) — retained but not part of Phase 1.1 plan spec
- tvkit credential fields (`tvkit_browser`, `tvkit_auth_token`) — retained for existing
  compatibility; Phase 1.3 will own these

---

## Gap Analysis

The repository already contained partial implementations of both target files. This section
documents the delta between the existing state and the Phase 1.1 plan specification.

### `constants.py` gaps

| Item | Existing | Required by Plan | Action |
|---|---|---|---|
| Benchmark symbol name | `SET_INDEX_SYMBOL` | `INDEX_SYMBOL` | Rename + update call sites |
| Sector codes type | `list[str]` (codes only) | `dict[str, str]` (code → name) | Change type + add names |
| Price floor name | `MIN_PRICE_THRESHOLD` | `MIN_PRICE_THB` | Rename + update call sites |
| History depth | missing | `LOOKBACK_YEARS: int = 15` | Add |
| Rebalance alias name | `REBALANCE_FREQUENCY` | `REBALANCE_FREQ` | Rename + update call sites |
| Rebalance alias value | `"ME"` (calendar month) | `"BME"` (business month) | Change value |

### `settings.py` gaps

| Item | Existing | Required by Plan | Action |
|---|---|---|---|
| `public_mode` default | `True` | `False` | Change default |
| `tvkit_concurrency` | missing | `int = 5`, `gt=0` | Add |
| `tvkit_retry_attempts` | missing | `int = 3`, `ge=0` | Add |
| `frozen` | not set | `frozen=True` | Add to `model_config` |
| Singleton accessor | `settings = Settings()` (mutable) | `get_settings()` with `lru_cache` | Add; keep as alias |
| `__all__` | missing `get_settings` | include `get_settings` | Update |

### Baseline test state

Before any edits, `uv run python -m pytest tests/` **fails at collection** due to two root causes:

1. `tests/conftest.py` top-level imports `from api.main import app` — which triggers a transitive
   import chain reaching `scipy`, a `research` group dependency not installed in the default `dev`
   environment.
2. The `api` module itself (Phases 5–6 deliverable) does not yet exist in `src/`.

**Mitigation (Phase 1.1 scope):** Move `api.*` imports inside the `client` fixture body in
`conftest.py`. This defers the ImportError to fixture invocation time rather than collection time,
making `tests/unit/config/` (and other unit test directories) fully collectable and runnable
without the API layer or `scipy`. The `client` fixture itself will fail at invocation until Phase
5–6, which is expected and acceptable.

---

## Design Decisions

### 1. Keep existing constants alongside plan-specified names

The existing file contains constants used by phases beyond 1.1 (e.g., `DEFAULT_LOOKBACK_MONTHS`,
`TIMEZONE`, `RISK_FREE_RATE_ANNUAL`, `TRANSACTION_COST_BPS`). These are **retained** — renaming
them falls outside Phase 1.1 scope and would cascade across features and risk modules. Only the
constants directly specified in the Phase 1.1 plan are renamed/added.

### 2. `MIN_AVG_DAILY_VOLUME` type: `float` kept over `int`

The plan specifies `int`, but the value (1,000,000 THB avg daily turnover) participates in float
arithmetic downstream. Retained as `float = 1_000_000.0` to avoid silent truncation in downstream
comparisons. This is a minor deviation from the plan's declared type, recorded here for
traceability.

### 3. `frozen=True` added; `get_settings()` exposes the singleton

`frozen=True` makes `Settings` instances immutable after construction, preventing accidental
mutation across test cases. The `get_settings()` function uses `@lru_cache(maxsize=1)` to return
the same instance for the process lifetime.

**Tests that need custom settings** must:

```python
from csm.config.settings import get_settings
monkeypatch.setenv("CSM_PUBLIC_MODE", "true")
get_settings.cache_clear()
s = get_settings()  # picks up new env
```

The module-level `settings = get_settings()` alias is kept for backward compatibility with
existing import sites until they migrate to `get_settings()`. Note: this alias resolves at import
time and will **not** reflect subsequent `cache_clear()` + `get_settings()` calls in the same
process. Tests that monkeypatch env vars must call `get_settings()` directly rather than relying
on the `settings` alias.

### 4. `REBALANCE_FREQ = "BME"` (business month-end)

Changed from `"ME"` (calendar month-end) to `"BME"` as specified by the plan. This ensures
rebalance dates land on the last business day of each month, which is the correct behaviour for
a strategy that trades on market close. `"BME"` is the non-deprecated business month-end alias in
pandas 2.2+.

### 5. `SET_SECTOR_CODES` changed to `dict[str, str]`

The plan specifies a sector code → sector name mapping. The eight SET industry groups are mapped
to their official English names as published on the SET website. This enables human-readable
logging and reporting without a separate lookup table.

### 6. Field constraints for `tvkit_concurrency` and `tvkit_retry_attempts`

Both fields use `pydantic.Field` with range constraints:

- `tvkit_concurrency: int = Field(default=5, gt=0, ...)` — concurrency of 0 would deadlock
- `tvkit_retry_attempts: int = Field(default=3, ge=0, ...)` — 0 retries is valid (no retry)

---

## Implementation Steps

### Step 1: Write this plan document (complete before any code changes)

Save `docs/plans/phase1_data_pipeline/phase1.1-config-and-constants.md`.

### Step 2: Record baseline state

```bash
git branch --show-current
git status
uv run python -m pytest tests/ -v 2>&1 | head -20  # confirm known collection failure
```

### Step 3: Fix `conftest.py` collection isolation

Move `from api.deps import set_store` and `from api.main import app` inside the `client` fixture
body. This unblocks collection for all unit test directories.

### Step 4: Update `constants.py`

- Rename `SET_INDEX_SYMBOL` → `INDEX_SYMBOL`
- Change `SET_SECTOR_CODES` from `list[str]` to `dict[str, str]` with official sector names
- Rename `MIN_PRICE_THRESHOLD` → `MIN_PRICE_THB`
- Add `LOOKBACK_YEARS: int = 15`
- Rename `REBALANCE_FREQUENCY` → `REBALANCE_FREQ`; change value `"ME"` → `"BME"`
- Update `__all__`

### Step 5: Update `settings.py`

- Add `frozen=True` to `SettingsConfigDict`
- Change `public_mode` default from `True` to `False`
- Add `tvkit_concurrency: int = Field(default=5, gt=0, ...)`
- Add `tvkit_retry_attempts: int = Field(default=3, ge=0, ...)`
- Add `get_settings()` with `@lru_cache(maxsize=1)`
- Update module-level `settings` to `settings = get_settings()`
- Update `__all__`

### Step 6: Update `config/__init__.py`

- Replace old constant names with new names in imports and `__all__`
- Add `LOOKBACK_YEARS` and `get_settings` to exports

### Step 7: Update call sites

- `src/csm/data/universe.py`: `MIN_PRICE_THRESHOLD` → `MIN_PRICE_THB`
- `src/csm/features/momentum.py`: `REBALANCE_FREQUENCY` → `REBALANCE_FREQ`

### Step 8: Create unit tests

- Create `tests/unit/config/__init__.py`
- Create `tests/unit/config/test_settings.py` with three tests

### Step 9: Run verification suite (see Verification Addendum)

### Step 10: Update `PLAN.md` and this document with completion notes; commit

---

## Verification Addendum

Run in this exact order to establish baseline, then validate changes:

```bash
# Baseline — record known state before any edits
git branch --show-current          # expect: feature/phase-1-data-pipeline
git status                         # expect: only pre-existing modifications
uv run python -m pytest tests/ -v 2>&1 | head -20   # expect: collection failure (api/scipy)

# After conftest.py fix — unit tests should now collect
uv run python -m pytest tests/unit/ -v --collect-only   # expect: clean collection

# After all code changes — run focused targets
uv run python -m pytest tests/unit/config/ -v           # must pass: 3 tests
uv run python -m mypy src/csm/config/                   # must exit 0
uv run ruff check src/csm/config/ \
    src/csm/data/universe.py \
    src/csm/features/momentum.py   # must exit 0
uv run ruff format --check src/csm/config/ \
    src/csm/data/universe.py \
    src/csm/features/momentum.py   # must exit 0

# Full unit suite — no regressions in existing unit tests
uv run python -m pytest tests/unit/ -v
```

---

## File Changes

| File | Action | Description |
|---|---|---|
| `src/csm/config/constants.py` | MODIFY | Rename constants, fix types, add `LOOKBACK_YEARS` |
| `src/csm/config/settings.py` | MODIFY | Add fields, `frozen=True`, `get_settings()` |
| `src/csm/config/__init__.py` | MODIFY | Update exports for new names |
| `src/csm/data/universe.py` | MODIFY | `MIN_PRICE_THRESHOLD` → `MIN_PRICE_THB` |
| `src/csm/features/momentum.py` | MODIFY | `REBALANCE_FREQUENCY` → `REBALANCE_FREQ` |
| `tests/conftest.py` | MODIFY | Move `api.*` imports inside `client` fixture body |
| `tests/unit/config/__init__.py` | CREATE | Package marker |
| `tests/unit/config/test_settings.py` | CREATE | Three unit tests |
| `docs/plans/phase1_data_pipeline/phase1.1-config-and-constants.md` | CREATE | This document |
| `docs/plans/phase1_data_pipeline/PLAN.md` | MODIFY | Phase 1.1 status + completion notes |

---

## Success Criteria

- [x] `INDEX_SYMBOL = "SET:SET"` present and exported from `csm.config`
- [x] `SET_SECTOR_CODES` is `dict[str, str]` with all eight SET industry groups
- [x] `MIN_PRICE_THB = 1.0` present and exported
- [x] `LOOKBACK_YEARS = 15` present and exported
- [x] `REBALANCE_FREQ = "BME"` present and exported
- [x] `Settings.public_mode` defaults to `False`
- [x] `Settings.tvkit_concurrency` defaults to `5`, constrained `gt=0`
- [x] `Settings.tvkit_retry_attempts` defaults to `3`, constrained `ge=0`
- [x] `Settings` is frozen (direct attribute assignment raises `ValidationError`)
- [x] `get_settings()` returns the same instance on repeated calls (lru_cache)
- [x] `tests/unit/config/` collects cleanly with no `api.*` import error
- [x] All three unit tests pass
- [x] `uv run mypy src/csm/config/` exits 0
- [x] `uv run ruff check src/csm/config/` exits 0
- [x] No regressions in `tests/unit/` (all existing unit tests still pass)

---

## Completion Notes

### Summary

Phase 1.1 complete. All constants renamed and added per plan spec. `Settings` extended with
`tvkit_concurrency`, `tvkit_retry_attempts`, `frozen=True`, and `get_settings()` lru_cache
singleton. `conftest.py` collection isolation fixed by moving `api.*` imports inside the `client`
fixture body. All call sites updated. Three unit tests written and passing. Quality gates pass.

### Issues Encountered

1. **`MIN_AVG_DAILY_VOLUME` type kept as `float`** — the plan specifies `int`, but the value
   (1,000,000 THB avg daily turnover) participates in float arithmetic downstream. Retained as
   `float` to avoid silent truncation. Documented in Design Decisions §2.

2. **`conftest.py` collection failure** — top-level `from api.main import app` imports triggered
   a transitive dependency chain reaching `scipy` (not installed in `dev` group). Fixed by moving
   `api.*` imports inside the `client` fixture body. The fixture itself will fail at invocation
   until the API layer is implemented (future phase).

3. **`settings` alias staleness in tests** — the module-level `settings = get_settings()` resolves
   at import time. Tests using `monkeypatch.setenv` + `get_settings.cache_clear()` must call
   `get_settings()` directly, not rely on the pre-bound `settings` alias. Documented in Design
   Decisions §3.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Sonnet 4.6)
**Status:** Complete
**Completed:** 2026-04-21
