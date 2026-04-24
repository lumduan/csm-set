# Phase 1.8 — Dividend Adjustment

**Feature:** Total-Return Price Series via tvkit Adjustment.DIVIDENDS
**Branch:** `feature/phase-1.8-dividend-adjustment`
**Created:** 2026-04-24
**Completed:** 2026-04-24
**Status:** Complete
**Depends On:** Phase 1.3 (OHLCVLoader — Complete), Phase 1.6 (fetch_history.py — Complete), Phase 1.7 (data quality sign-off — Complete)

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Problem Statement](#problem-statement)
4. [Design Decisions](#design-decisions)
5. [Scope](#scope)
6. [Implementation Steps](#implementation-steps)
7. [File Changes](#file-changes)
8. [Testing Strategy](#testing-strategy)
9. [Success Criteria](#success-criteria)
10. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 1.8 upgrades the data pipeline to use **total-return (dividend-adjusted)** OHLCV prices
for all SET universe symbols. tvkit v0.11.0 will introduce the `Adjustment` enum with an
`Adjustment.DIVIDENDS` member that instructs TradingView to backward-adjust all prior bars
for cash dividend payments.

All data fetched in Phases 1.3–1.6 used the implicit `Adjustment.SPLITS` default, which
adjusts only for stock splits. For long-term momentum backtesting on SET stocks — many of
which pay regular dividends — split-only-adjusted prices understate compounded historical
performance and introduce systematic bias in cross-sectional momentum rankings.

### Key Concept: Why Dividend Adjustment Matters

When a company pays a cash dividend on day *t*, the stock price drops by approximately that
amount on the ex-dividend date. With `Adjustment.SPLITS` (the old default), that drop is visible
in the price series as an apparent loss. With `Adjustment.DIVIDENDS`, all prior bars are
backward-adjusted downward so the price series reflects the *continuous total return* an
investor would have received — the price drop on the ex-date disappears.

**Example (SET:ADVANC):**

```python
from tvkit.api.chart import OHLCV, Adjustment

async with OHLCV() as client:
    splits_bars = await client.get_historical_ohlcv(
        "SET:ADVANC", "1D", bars_count=300,
        adjustment=Adjustment.SPLITS,
    )
    div_bars = await client.get_historical_ohlcv(
        "SET:ADVANC", "1D", bars_count=300,
        adjustment=Adjustment.DIVIDENDS,
    )

# Dividend-adjusted close is LOWER than split-adjusted for the same historical bar
# because past prices are adjusted down to absorb each dividend payment.
print(splits_bars[0].close)   # e.g. 280.0  — split-only adjusted
print(div_bars[0].close)      # e.g. 254.9  — total-return adjusted (lower)
```

For momentum signals (12-1 month return ranking), using total-return prices ensures that
high-dividend stocks are not systematically penalised in cross-sectional rankings.

### Parent Plan Reference

- `docs/plans/phase1_data_pipeline/PLAN.md` — Phase 1.8 section

### Storage Layout After Phase 1.8

```text
data/raw/
├── splits/        ← migrated from Phase 1.6 (split-adjusted, backward-compat)
│   └── SET%3AAOT.parquet
└── dividends/     ← Phase 1.8 re-fetch (total-return adjusted — default going forward)
    └── SET%3AAOT.parquet
```

---

## AI Prompt

The following prompt was used to generate this phase:

```text
🎯 Objective
Implement plan and execution workflow for Phase 1.8 — Dividend Adjustment of the csm-set data
pipeline, following the project's architectural, documentation, and workflow standards. The plan
should be documented in a new markdown file, and the implementation should proceed only after
the plan is complete. All progress and completion notes must be updated in the relevant
documentation files.

📋 Context
- The csm-set project is a production-grade, type-safe, async-first Python data pipeline for
  SET OHLCV data.
- Phase 1.8 — Dividend Adjustment aims to re-fetch all SET universe symbols using tvkit's
  Adjustment.DIVIDENDS to produce total-return price series.
- The project enforces strict architectural, documentation, and workflow standards (see
  .github/instructions/).
- The main plan is in docs/plans/phase1_data_pipeline/PLAN.md, with Phase 1.8 requirements
  and deliverables detailed in the "Dividend Adjustment" section.
- All new plans must be written to docs/plans/phase1_data_pipeline/{phase_name_of_phase}.md
  and include the prompt used.
- All progress and completion notes must be reflected in both the master plan and the
  phase-specific plan.
- All code changes must be committed on a new git branch.

🔧 Requirements
- Read and understand docs/plans/phase1_data_pipeline/PLAN.md, focusing on Phase 1.8.
- Before coding, create a detailed implementation plan in markdown at
  docs/plans/phase1_data_pipeline/phase1.8-dividend-adjustment.md, including the prompt used.
- The plan must follow the format in docs/plans/examples/phase1-sample.md.
- After the plan is complete, implement the required changes:
  - Update pyproject.toml to require tvkit>=0.11.0.
  - Add tvkit_adjustment: str = "dividends" to src/csm/config/settings.py.
  - Update src/csm/data/loader.py to support an adjustment parameter, using the Adjustment
    enum from tvkit.
  - Update scripts/fetch_history.py and scripts/build_universe.py to support an --adjustment
    CLI flag and store data under the correct subdirectory.
  - Update src/csm/data/universe.py to accept the correct raw store.
  - Add or update unit tests for all changes.
  - Re-run the fetch script to populate data/raw/dividends/.
  - Update the data quality notebook to verify price adjustment.
- After implementation, update both docs/plans/phase1_data_pipeline/PLAN.md and
  docs/plans/phase1_data_pipeline/phase1.8-dividend-adjustment.md with progress notes,
  completion status, and any issues encountered.
- All code and documentation must follow project standards for type safety, async patterns,
  Pydantic validation, error handling, and documentation.
- All changes must be committed with a clear, standards-compliant commit message.

📁 Code Context
- docs/plans/phase1_data_pipeline/PLAN.md (master plan)
- docs/plans/examples/phase1-sample.md (plan format reference)
- src/csm/config/settings.py (settings model)
- src/csm/data/loader.py (OHLCVLoader)
- scripts/fetch_history.py (bulk fetch script)
- scripts/build_universe.py (universe builder script)
- src/csm/data/universe.py (universe builder)
- pyproject.toml (dependency management)
- notebooks/01_data_exploration.ipynb (data quality notebook)
- .github/instructions/ (project standards)

✅ Expected Output
- A new plan file: docs/plans/phase1_data_pipeline/phase1.8-dividend-adjustment.md with a
  detailed implementation plan and the prompt used.
- Implementation of all required changes for Phase 1.8 as described above.
- Updated documentation in both the master plan and the phase-specific plan, with progress
  and completion notes.
- All code and documentation changes committed on a new branch with a standards-compliant
  commit message.
```

---

## Problem Statement

1. **Biased momentum signals** — Phase 1.6 raw data uses `Adjustment.SPLITS`. On ex-dividend
   dates, the price series shows a step-down that reads as a negative return, making
   high-dividend stocks look worse than they are on a total-return basis.

2. **No mechanism to request dividend adjustment** — `OHLCVLoader.fetch()` hard-codes
   `get_historical_ohlcv()` without an `adjustment` argument, so there is no way to
   switch modes without code changes.

3. **No settings field for adjustment mode** — the pipeline cannot be configured at runtime
   to switch between `splits` and `dividends` without patching source code.

4. **Existing `data/raw/` data is split-adjusted only** — all parquet files on disk must be
   re-fetched or clearly namespaced to avoid silently mixing the two adjustment types in
   downstream consumers.

---

## Design Decisions

### Decision 1 — Adjustment-Scoped Storage Directories

Store raw OHLCV data under a subdirectory named after the adjustment mode:

```text
data/raw/
├── splits/      ← legacy Phase 1.6 data (split-adjusted)
└── dividends/   ← Phase 1.8 re-fetch (total-return adjusted — default going forward)
```

**Rationale:**

- Prevents accidental mixing of adjustment types in `UniverseBuilder` and `PriceCleaner`.
- Keeps the existing Phase 1.6 data accessible for comparison without re-fetch.
- `ParquetStore` requires no changes — the `base_dir` is passed by the caller; changing
  `data/raw/` to `data/raw/dividends/` is a one-line change in each script.
- A one-time migration step in `fetch_history.py` moves existing flat `data/raw/*.parquet`
  files into `data/raw/splits/` so the directory contract is satisfied retroactively.

**Alternative rejected:** key prefix (`"dividends/SET:AOT"`) inside the same store — this
would require updating every `store.list_keys()` filter and `store.load()` call throughout
the pipeline.

### Decision 2 — `tvkit_adjustment` as a Settings Field

Add `tvkit_adjustment: str = "dividends"` to `Settings` so the adjustment mode is
environment-configurable without code changes. The field is validated against the two
known values (`"splits"` / `"dividends"`) via a Pydantic `field_validator`.

### Decision 3 — Local `Adjustment` Enum — No tvkit 0.11.0 Import Yet

tvkit is currently at version 0.6.0. The `Adjustment` enum will be introduced in tvkit 0.11.0
which has not shipped yet. To keep the pipeline's storage layout, CLI flags, and settings
complete now without breaking `uv sync`, we define a local `Adjustment(str, Enum)` in
`loader.py` that mirrors the planned tvkit API.

**Consequence:** In this phase the actual per-bar prices from tvkit are still split-adjusted
(tvkit 0.6.0 does not support the `adjustment` parameter). The storage layout, CLI flags,
and defaults are all wired up correctly. When tvkit 0.11.0 ships, only two changes are needed:

1. Replace the local `Adjustment` enum import with `from tvkit.api.chart import Adjustment`
2. Bump `pyproject.toml` to `tvkit>=0.11.0`
3. Add `adjustment=adj_enum` kwarg to the `client.get_historical_ohlcv()` call in `loader.py`

### Decision 4 — `pyproject.toml` tvkit Pin Kept at `>=0.4`

Bumping to `>=0.11.0` would break `uv sync` immediately since that release does not exist.
The constraint stays at `>=0.4` with a `# TODO: bump to >=0.11.0 when released` comment.
This is documented here as a known gap from the spec; the bump will be the first change
made once tvkit 0.11.0 ships.

### Decision 5 — `adjustment` Parameter as `str | None` on `OHLCVLoader`

`OHLCVLoader.fetch()` and `fetch_batch()` accept an explicit `adjustment: str | None = None`
parameter. When `None`, the effective adjustment falls back to `settings.tvkit_adjustment`.
The string is coerced to the local `Adjustment` enum before use so unknown strings raise
`ValueError` before any network I/O.

### Decision 6 — Default adjustment is `"dividends"`

`fetch_history.py --adjustment` defaults to `dividends`. This ensures all future fetches
produce total-return series by default. The old `data/raw/*.parquet` files are migrated to
`data/raw/splits/` automatically on first run, preserving backward compatibility.

### Decision 7 — One-Time Migration in `fetch_history.py`

On startup, `_migrate_legacy_raw()` checks whether `data/raw/` contains `.parquet` files
directly (not inside a subdirectory). If yes, they are moved to `data/raw/splits/`. This
migration is idempotent (safe to re-run) and logged. It runs before any fetch and before
store instantiation so the idempotency check uses the correct subdirectory.

---

## Scope

### In Scope

| Component | Change |
| --- | --- |
| `src/csm/config/settings.py` | Add `tvkit_adjustment: str = "dividends"` with validator |
| `src/csm/data/loader.py` | Add local `Adjustment` enum; add `adjustment` param to `fetch()` / `fetch_batch()` |
| `scripts/fetch_history.py` | Add `--adjustment` flag; adjustment-scoped `raw_dir`; one-time migration of legacy flat files |
| `scripts/build_universe.py` | Add `--adjustment` flag; pass scoped store to `UniverseBuilder` |
| Unit tests | Update / add for all changed modules |
| `notebooks/01_data_exploration.ipynb` | Add Section 7: Price Adjustment Verification |

### Out of Scope

- `pyproject.toml` tvkit bump to `>=0.11.0` — deferred until tvkit 0.11.0 ships (see Decision 4)
- `src/csm/data/universe.py` — no changes needed; already accepts explicit `store: ParquetStore`
- `PriceCleaner` — winsorisation bounds are adjustment-agnostic
- `ParquetStore` — no API changes; only the `base_dir` caller argument changes
- Incremental refresh logic (Phase 5)
- Populating `data/raw/dividends/` with genuine total-return prices — deferred until tvkit 0.11.0 ships

---

## Implementation Steps

### Step 1 — Add `tvkit_adjustment` to Settings

**File:** `src/csm/config/settings.py`

Add the field and a Pydantic `field_validator`:

```python
from pydantic import Field, field_validator

# Inside Settings class:
tvkit_adjustment: str = Field(
    default="dividends",
    description=(
        "Price adjustment mode for OHLCV fetches. "
        "'dividends' — total-return backward adjustment (recommended for backtesting). "
        "'splits' — split-adjusted only (legacy pre-v0.11.0 behaviour)."
    ),
)

@field_validator("tvkit_adjustment")
@classmethod
def _validate_adjustment(cls, value: str) -> str:
    allowed: set[str] = {"splits", "dividends"}
    if value not in allowed:
        raise ValueError(
            f"tvkit_adjustment must be one of {sorted(allowed)!r}, got {value!r}"
        )
    return value
```

Env var: `CSM_TVKIT_ADJUSTMENT=dividends` (default) or `CSM_TVKIT_ADJUSTMENT=splits`.

---

### Step 2 — Add `Adjustment` Enum and `adjustment` Parameter to `OHLCVLoader`

**File:** `src/csm/data/loader.py`

#### 2a — Add local `Adjustment` enum

```python
from enum import Enum

class Adjustment(str, Enum):
    """Price adjustment mode for historical OHLCV fetches.

    Mirrors the Adjustment enum planned for tvkit v0.11.0.
    Replace this local definition with the tvkit import once tvkit>=0.11.0 ships.
    """
    SPLITS = "splits"
    DIVIDENDS = "dividends"
```

#### 2b — Update `fetch()` signature

```python
async def fetch(
    self,
    symbol: str,
    interval: str,
    bars: int,
    adjustment: str | None = None,
) -> pd.DataFrame:
```

Resolve the effective adjustment before the tvkit call:

```python
effective: str = adjustment if adjustment is not None else self._settings.tvkit_adjustment
adj_enum: Adjustment = Adjustment(effective)  # raises ValueError on unknown string
```

Pass to tvkit (no-op until tvkit 0.11.0; the kwarg will be added then):

```python
# TODO: pass adjustment=adj_enum once tvkit>=0.11.0 ships
bars_data = await client.get_historical_ohlcv(symbol, interval=interval, bars_count=bars)
```

#### 2c — Update `fetch_batch()` signature

```python
async def fetch_batch(
    self,
    symbols: list[str],
    interval: str,
    bars: int,
    adjustment: str | None = None,
) -> dict[str, pd.DataFrame]:
```

Forward `adjustment` to `self.fetch()` inside `_fetch_symbol`.

---

### Step 3 — Update `fetch_history.py`

**File:** `scripts/fetch_history.py`

#### 3a — Add `--adjustment` CLI argument

```python
parser.add_argument(
    "--adjustment",
    choices=["splits", "dividends"],
    default=None,
    help=(
        "Price adjustment mode. Overrides CSM_TVKIT_ADJUSTMENT env var. "
        "Use 'dividends' (default) for total-return momentum backtesting. "
        "Use 'splits' to reproduce legacy Phase 1.6 data."
    ),
)
```

#### 3b — Determine `raw_dir` from adjustment mode

```python
adjustment_mode: str = args.adjustment or app_settings.tvkit_adjustment
raw_dir: Path = data_dir / "raw" / adjustment_mode
```

#### 3c — One-time migration of legacy flat files

```python
def _migrate_legacy_raw(raw_root: Path) -> None:
    """Move flat Phase 1.6 parquet files into raw_root/splits/ if needed."""
    splits_dir: Path = raw_root / "splits"
    legacy_files: list[Path] = list(raw_root.glob("*.parquet"))
    if not legacy_files:
        return
    splits_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for src in legacy_files:
        dst: Path = splits_dir / src.name
        if not dst.exists():
            src.rename(dst)
            moved += 1
    logger.info("Migration: moved %d legacy file(s) to %s", moved, splits_dir)
```

Call `_migrate_legacy_raw(data_dir / "raw")` at startup before store instantiation.

#### 3d — Pass `adjustment` to `OHLCVLoader.fetch_batch()`

```python
results = await loader.fetch_batch(pending, "1D", args.bars, adjustment=adjustment_mode)
```

#### 3e — Include `adjustment_mode` in failures JSON

```python
failures_data = {
    "run_timestamp": run_timestamp.isoformat(),
    "adjustment": adjustment_mode,
    "failed_symbols": failed,
    "count": len(failed),
}
```

---

### Step 4 — Update `build_universe.py`

**File:** `scripts/build_universe.py`

Add `--adjustment {splits,dividends}` argument (default: `"dividends"`).
Instantiate the raw store at `data_dir / "raw" / adjustment_mode`:

```python
adjustment_mode: str = args.adjustment or app_settings.tvkit_adjustment
raw_store = ParquetStore(data_dir / "raw" / adjustment_mode)
builder = UniverseBuilder(raw_store, app_settings)
```

---

### Step 5 — Unit Tests

| Test file | Changes |
| --- | --- |
| `tests/unit/config/test_settings.py` | Add: `tvkit_adjustment` defaults to `"dividends"`; validator rejects invalid values |
| `tests/unit/data/test_loader.py` | Add: `fetch` stores `Adjustment` enum; unknown string raises `ValueError`; default falls back to settings |
| `tests/unit/scripts/test_fetch_history.py` | Add: `--adjustment` flag path derivation; migration moves flat `.parquet` files |

---

### Step 6 — Notebook Section 7

**File:** `notebooks/01_data_exploration.ipynb`

Add Section 7 — Price Adjustment Verification (การตรวจสอบการปรับราคาเงินปันผล):

1. Markdown header cell (Thai) explaining `Adjustment.SPLITS` vs `Adjustment.DIVIDENDS`
2. Load `SET:ADVANC` (or first available high-dividend symbol) from both stores with guards
3. Overlay line chart: splits-adjusted vs dividend-adjusted close over available history
4. Print `⚠ NOTE: tvkit<0.11.0 — both series identical until upgrade` if prices match exactly
5. PASS gate: `data/raw/dividends/` store has ≥ 1 symbol loaded successfully

---

## File Changes

| File | Type | Description |
| --- | --- | --- |
| `src/csm/config/settings.py` | Modify | Add `tvkit_adjustment` field + validator |
| `src/csm/data/loader.py` | Modify | Add local `Adjustment` enum; add `adjustment` param to `fetch()` and `fetch_batch()` |
| `scripts/fetch_history.py` | Modify | `--adjustment` flag; scoped `raw_dir`; legacy migration helper |
| `scripts/build_universe.py` | Modify | `--adjustment` flag; scoped raw store |
| `tests/unit/config/test_settings.py` | Modify | New test cases for `tvkit_adjustment` |
| `tests/unit/data/test_loader.py` | Modify | New test cases for `adjustment` parameter |
| `tests/unit/scripts/test_fetch_history.py` | Modify | New test cases for `--adjustment` flag and migration |
| `notebooks/01_data_exploration.ipynb` | Modify | Add Section 7: Price Adjustment Verification |
| `docs/plans/phase1_data_pipeline/PLAN.md` | Modify | Completion notes for Phase 1.8 |
| `docs/plans/phase1_data_pipeline/phase1.8-dividend-adjustment.md` | Create | This document |

---

## Testing Strategy

### Unit Tests (no real API calls)

- Mock `tvkit.OHLCV.get_historical_ohlcv` with `AsyncMock`; assert the `adjustment` kwarg is
  stored on the loader instance and the enum is correctly resolved.
- Test default resolution: when `adjustment=None`, the `settings.tvkit_adjustment` value is used.
- Test `ValueError` propagation: unknown string raises `ValueError` before any tvkit call.
- Test `fetch_batch` forwards `adjustment` to each per-symbol `fetch` call.
- Test `Settings` validator: `"dividends"` and `"splits"` accepted; other values raise on model construction.
- Test `fetch_history.py` path resolution: `--adjustment dividends` produces store at
  `data_dir/raw/dividends/`; `--adjustment splits` produces `data_dir/raw/splits/`.
- Test legacy migration: flat `.parquet` files in `data/raw/` are moved to `data/raw/splits/`
  on first run; subsequent runs are idempotent (files already moved, no-op).

### Manual Integration Check (skipped in CI)

After re-fetching with `--adjustment dividends` (post tvkit 0.11.0):

1. Load `SET:ADVANC` from both `data/raw/splits/` and `data/raw/dividends/`.
2. Assert the earliest dividend-adjusted close < earliest splits-adjusted close.
3. Assert mean daily return (dividends) > mean daily return (splits) for the same symbol.

---

## Success Criteria

| Criterion | Measure |
| --- | --- |
| `Settings.tvkit_adjustment` defaults to `"dividends"` | Unit test: `Settings().tvkit_adjustment == "dividends"` |
| `Settings(tvkit_adjustment="invalid")` raises `ValidationError` | Unit test |
| `OHLCVLoader.fetch()` signature accepts `adjustment` kwarg | Unit test: call with `adjustment="splits"` succeeds |
| Unknown `adjustment` string raises `ValueError` before network I/O | Unit test |
| `--adjustment dividends` stores data in `data/raw/dividends/` | Unit test: path assertion |
| `--adjustment splits` stores data in `data/raw/splits/` | Unit test: path assertion |
| Legacy flat files migrated to `data/raw/splits/` on first run | Unit test + manual |
| Migration is idempotent | Unit test |
| All unit tests pass | `uv run pytest tests/ -v -m "not integration"` exits 0 |
| Type checking clean | `uv run mypy src/` exits 0 |
| Linting clean | `uv run ruff check src/ scripts/` exits 0 |
| Notebook Section 7 renders without error | Manual: run all cells |

---

## Completion Notes

### Summary

Phase 1.8 complete (2026-04-24). All pipeline wiring, storage layout, CLI flags, settings
field, unit tests, and notebook section implemented in a single session on branch
`feature/phase-1.8-dividend-adjustment`.

### Issues Encountered

1. **tvkit 0.11.0 not yet released** — The `Adjustment` enum and `adjustment` kwarg planned for
   tvkit 0.11.0 do not exist in the currently installed tvkit 0.6.0. A local `Adjustment(StrEnum)`
   was defined in `loader.py` to mirror the planned API. The `pyproject.toml` tvkit constraint
   was left at `>=0.4` to avoid breaking `uv sync`. When tvkit 0.11.0 ships: replace the local
   enum with the tvkit import, bump the pin, and add `adjustment=adj_enum` to the
   `client.get_historical_ohlcv()` call.

2. **ruff UP042** — Initial `class Adjustment(str, Enum)` triggered ruff UP042. Changed to
   `class Adjustment(StrEnum)` (Python 3.11+ StrEnum), which ruff accepts and mypy verifies.

3. **Test path updates** — 5 existing `test_fetch_history.py` assertions referenced the old
   flat `data/raw/fetch_failures.json` path; all updated to the new scoped path
   `data/raw/<adjustment>/fetch_failures.json`.

4. **Notebook `raw_store` path** — The notebook setup cell originally pointed to `data/raw/`
   directly. After Phase 1.8 the migrated data lives in `data/raw/splits/`. Updated the setup
   cell to auto-detect: prefers `data/raw/splits/` if populated, falls back to `data/raw/` for
   pre-migration repos.

---

Document Version: 1.1
Author: AI Agent (Claude Sonnet 4.6)
Status: Complete
Completed: 2026-04-24
