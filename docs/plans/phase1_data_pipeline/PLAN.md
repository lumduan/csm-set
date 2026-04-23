# Phase 1 — Data Pipeline Master Plan

**Feature:** Reliable OHLCV Data Pipeline for All SET Symbols
**Branch:** `feature/phase-1-data-pipeline`
**Created:** 2026-04-21
**Status:** Complete — all sub-phases 1.1–1.7 done (2026-04-23)
**Positioning:** Foundation layer — all signal research, backtesting, and portfolio construction depend on clean, versioned parquet data produced here

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

Phase 1 builds the **data pipeline** that makes the entire csm-set system possible. It ingests raw OHLCV data for all SET-listed symbols via tvkit, applies deterministic cleaning, assembles dated universe snapshots, and writes everything to versioned parquet files. Every downstream phase (Signal Research, Backtesting, Portfolio Construction, API, Dashboard) depends entirely on the artefacts produced here.

### Scope

Phase 1 covers seven sub-phases in dependency order:

| Sub-phase | Deliverable | Purpose |
|---|---|---|
| 1.1 | Config & Constants | `Settings` model + SET-specific constants |
| 1.2 | Storage Layer | `ParquetStore` — save / load / exists / list |
| 1.3 | tvkit Loader | `OHLCVLoader` — async fetch with retry |
| 1.4 | Universe Builder | Filtered symbol list + dated snapshots |
| 1.5 | Price Cleaner | Gap-fill, winsorise, drop low-coverage symbols |
| 1.6 | Bulk Fetch Script | `scripts/fetch_history.py` — idempotent 20-year pull |
| 1.7 | Data Quality Check | `01_data_exploration.ipynb` — audit and sign-off |

**Out of scope for Phase 1:**

- Momentum signal calculation (Phase 2)
- Backtesting engine (Phase 3)
- API or UI layer (Phases 5–6)
- Any live or scheduled data refresh (Phase 5)

### Public Mode Boundary

This phase introduces `public_mode: bool` in `Settings`. When `CSM_PUBLIC_MODE=true`, `OHLCVLoader` raises `DataAccessError` immediately on any fetch attempt — the pipeline cannot run without tvkit credentials. All downstream public-mode consumers read from pre-computed `results/` artefacts, never from the live data layer built here.

---

## Problem Statement

The csm-set strategy requires accurate, survivorship-bias-safe daily OHLCV data for 400+ SET symbols spanning 15+ years. Several non-trivial problems must be solved before any quantitative research is possible:

1. **No data on disk yet** — the raw OHLCV store does not exist; every run must fetch from tvkit, which is slow and rate-limited.
2. **Idempotency** — re-running the fetch script must not re-download already-fetched symbols or corrupt existing parquet files.
3. **Public mode safety** — the public-facing Docker image must never attempt to call tvkit (no credentials available). Any code path that accesses live data must raise immediately when `CSM_PUBLIC_MODE=true`.
4. **Data quality** — SET includes thinly traded names, suspended symbols, and gap-heavy histories. Signals computed on uncleaned data produce spurious results.
5. **Universe definition** — the tradeable universe must be defined deterministically and dated (one snapshot per rebalance date) to avoid survivorship bias in downstream research.
6. **Reproducibility** — a contributor cloning the repo must be able to reproduce the full data pipeline from a `.env` file with valid tvkit credentials and a single script.

---

## Design Rationale

### Parquet as the Storage Format

Parquet is columnar, compressed, and natively supported by pandas and pyarrow. It preserves DataFrame dtypes (including DatetimeIndex with timezone info) across save/load cycles. CSV would lose dtype information and be 5–10× larger on disk. Parquet files are gitignored; only derived `results/` artefacts (NAV curves, z-scores, quintiles) are committed.

### Async Fetch with Concurrency Limit

tvkit's `OHLCV` API is async. `OHLCVLoader.fetch_batch()` runs concurrent fetches with `asyncio.Semaphore` to stay within tvkit's rate limit. Sequential fetching of 400+ symbols would take hours; controlled concurrency brings it to minutes.

### Deterministic Universe Snapshots

Rather than a single static symbol list, the universe is stored as dated snapshots: one parquet file per rebalance date containing the symbols eligible that month. This is the only way to avoid survivorship bias — a backtest using a 2024 symbol list applied to 2010 data silently includes companies that only became liquid after 2010.

### Settings via pydantic-settings

All runtime configuration is in a single `Settings` class (pydantic-settings `BaseSettings`). This makes the public mode flag, tvkit credentials, directory paths, and tunable thresholds injectable via environment variables and `.env`, with full type safety and validation at startup. No hardcoded constants outside `constants.py`.

### Fail-Fast on Public Mode

`OHLCVLoader` checks `settings.public_mode` before any network call and raises `DataAccessError` immediately. The check is in the loader, not scattered across scripts, so every call site is protected automatically.

### Repository Layout Validation

This plan matches the current repository layout and does not introduce speculative paths. The implementation targets the existing `src/csm/` package, the existing `notebooks/` directory, and the existing gitignored `data/` tree (`data/raw/`, `data/processed/`, `data/universe/`). Phase 1 work should be executed against those paths directly rather than assuming a future reorganisation.

### DataFrame Boundary and Pydantic Compliance

Project instructions require typed, validated boundaries, and this phase keeps that rule for configuration, settings, exceptions, and public-facing contracts. The explicit exception is the internal OHLCV tabular payload: pandas `DataFrame` is the canonical in-memory container for columnar price history because parquet I/O, rolling-window analytics, gap analysis, and vectorised cleaning are all DataFrame-native operations. To keep the architecture defensible, every pipeline boundary that accepts or returns OHLCV tabular data must enforce the documented DataFrame schema, while all non-tabular structures remain fully typed and Pydantic-validated.

---

## Architecture

### Directory Layout

```
src/csm/
├── config/
│   ├── constants.py          # SET sector codes, index symbol, thresholds (no env vars)
│   └── settings.py           # Settings(BaseSettings) — env var binding via pydantic-settings
├── data/
│   ├── store.py              # ParquetStore — save / load / exists / list_keys
│   ├── loader.py             # OHLCVLoader — async tvkit wrapper + DataAccessError
│   ├── universe.py           # UniverseBuilder — filter + dated snapshots
│   └── cleaner.py            # PriceCleaner — gap-fill / winsorise / drop

scripts/
├── fetch_history.py          # Entry point: fetch 20Y history for universe symbols
└── build_universe.py         # Entry point: build dated universe snapshots

data/                         # gitignored entirely
├── raw/                      # One parquet per symbol: {SYMBOL}.parquet
├── processed/                # Cleaned OHLCV after PriceCleaner
└── universe/                 # symbols.json + dated snapshots

notebooks/
└── 01_data_exploration.ipynb # Data quality audit notebook

tests/
├── config/
│   └── test_settings.py
├── data/
│   ├── test_store.py
│   ├── test_loader.py
│   ├── test_universe.py
│   └── test_cleaner.py
```

This directory layout is already present in the repository today: `src/csm/` exists as the application package root, `notebooks/` already contains the exploratory notebooks, and `data/` already contains `raw/`, `processed/`, and `universe/` directories. Phase 1 should extend these existing locations rather than creating parallel alternatives.

### Dependency Graph

```
Settings + constants (no deps)
    ↑ used by
ParquetStore          (pyarrow, pandas — no tvkit)
    ↑ used by
OHLCVLoader           (tvkit, asyncio — checks public_mode)
    ↑ used by
UniverseBuilder       (OHLCVLoader, ParquetStore)
    ↑ used by
PriceCleaner          (pandas, numpy — pure transform, no I/O)
    ↑ used by
fetch_history.py      (OHLCVLoader, ParquetStore)
build_universe.py     (UniverseBuilder, ParquetStore)
```

### Data Flow

```
tvkit OHLCV API
    ↓  OHLCVLoader.fetch_batch()
data/raw/{SYMBOL}.parquet           ← raw, uncleaned
    ↓  PriceCleaner
data/processed/{SYMBOL}.parquet     ← gap-filled, winsorised
    ↓  UniverseBuilder
data/universe/symbols.json          ← full candidate list
data/universe/{YYYY-MM-DD}.parquet  ← dated snapshots per rebalance date
```

---

## Implementation Phases

### Phase 1.1 — Config & Constants

**Status:** `[x]` Complete — 2026-04-22
**Plan:** `docs/plans/phase1_data_pipeline/phase1.1-config-and-constants.md`

**Goal:** Establish the typed configuration layer that all other sub-phases depend on. No business logic here — only settings and compile-time constants.

**Deliverables:**

- [x] `src/csm/config/constants.py`
  - [x] `INDEX_SYMBOL: str = "SET:SET"` — benchmark symbol for tvkit
  - [x] `SET_SECTOR_CODES: dict[str, str]` — sector code → sector name mapping
  - [x] `MIN_PRICE_THB: float = 1.0` — universe filter floor
  - [x] `MIN_AVG_DAILY_VOLUME: float = 1_000_000.0` — liquidity threshold (THB avg daily turnover; `float` retained over plan's `int` to avoid truncation in downstream arithmetic)
  - [x] `MIN_DATA_COVERAGE: float = 0.80` — 80% minimum valid bars in lookback window
  - [x] `LOOKBACK_YEARS: int = 15` — history depth for full backtest
  - [x] `REBALANCE_FREQ: str = "BME"` — pandas offset alias for business month-end
- [x] `src/csm/config/settings.py`
  - [x] `class Settings(BaseSettings)` with `model_config = SettingsConfigDict(env_prefix="CSM_", env_file=".env", frozen=True)`
  - [x] `public_mode: bool = False` — blocks data access when `CSM_PUBLIC_MODE=true`
  - [x] `results_dir: Path = Path("./results")` — output root for git-committed artefacts
  - [x] `data_dir: Path = Path("./data")` — gitignored data root
  - [x] `tvkit_concurrency: int = 5` — semaphore limit for `fetch_batch`, constrained `gt=0`
  - [x] `tvkit_retry_attempts: int = 3` — retry count for transient errors, constrained `ge=0`
  - [x] `log_level: str = "INFO"`
  - [x] `get_settings()` singleton via `@lru_cache(maxsize=1)`
- [x] Unit test: `Settings` loads correctly with correct defaults
- [x] Unit test: `Settings.public_mode` defaults to `False` with no env var set
- [x] Unit test: `Settings.public_mode` is `True` when `CSM_PUBLIC_MODE=true` in env
- [x] Unit test: `get_settings()` returns cached singleton
- [x] Unit test: `Settings` is frozen (attribute assignment raises)

**Implementation notes:**

- `constants.py` uses only Python builtins — no pydantic, no env vars
- `pydantic-settings>=2.3` is already declared in `pyproject.toml`
- `Settings` is a singleton: `get_settings()` with `functools.lru_cache(maxsize=1)`
- `.gitignore` `data/` pattern fixed to `/data/` — the unanchored form was silently excluding all of `src/csm/data/` from git tracking
- `tests/conftest.py` `client` fixture updated: `api.*` imports moved inside body to fix pytest collection for unit-only runs

---

### Phase 1.2 — Storage Layer

**Status:** `[x]` Complete — 2026-04-22
**Plan:** `docs/plans/phase1_data_pipeline/phase1.2-storage-layer.md`

**Goal:** Encapsulate all parquet I/O behind a single class. Callers never touch pyarrow or file paths directly.

**Deliverables:**

- [x] `src/csm/data/store.py` — `ParquetStore`
  - [x] `__init__(self, base_dir: Path)` — accepts data root, creates directory if absent
  - [x] `save(key: str, df: pd.DataFrame) -> None` — writes `{base_dir}/{encoded_key}.parquet`; overwrites if exists
  - [x] `load(key: str) -> pd.DataFrame` — reads and returns DataFrame; raises `KeyError` if not found
  - [x] `exists(key: str) -> bool` — returns `True` if the parquet file exists (`is_file()`)
  - [x] `list_keys() -> list[str]` — returns sorted list of all stored keys (recursive glob, POSIX-normalised)
  - [x] `delete(key: str) -> None` — removes the file; raises `KeyError` if not found
  - [x] `_validate_key()` — rejects empty, whitespace, backslash, and `..` traversal keys
- [x] Unit test: round-trip `save → load` preserves `DatetimeIndex` with UTC timezone
- [x] Unit test: round-trip preserves `float64` and `int64` column dtypes
- [x] Unit test: `save` returns `None`
- [x] Unit test: overwrite with same key succeeds; subsequent `load` returns updated data
- [x] Unit test: `load` raises `KeyError` for missing key
- [x] Unit test: `exists` returns `False` before save, `True` after save
- [x] Unit test: `list_keys` returns sorted canonical keys (e.g. `["SET:ADVANC", "SET:AOT"]`)
- [x] Unit test: `delete` removes file; subsequent `delete` raises `KeyError`

**Implementation notes:**

- Key encoding uses `urllib.parse.quote(key, safe="/")` — fully reversible percent-encoding; handles `%` and `:` in keys; safe on Windows and macOS
- `ParquetStore` is synchronous — documented architectural exception in module docstring; callers that need non-blocking I/O should wrap with `asyncio.to_thread()`
- `path.is_file()` used throughout instead of `path.exists()` to exclude directories named `*.parquet`
- `list_keys()` uses `rglob("*.parquet")` with `.as_posix()` for Windows-safe key reconstruction
- `tests/unit/data/__init__.py` created — package marker that aligns data test dir with `tests/unit/config/` convention

---

### Phase 1.3 — tvkit Loader

**Status:** `[x]` Complete — 2026-04-22
**Plan:** `docs/plans/phase1_data_pipeline/phase1.3-tvkit-loader.md`

**Goal:** Thin, testable async wrapper around tvkit `OHLCV`. Enforces public mode guard, handles concurrency, retries transient failures, and returns DataFrames with a documented schema.

**Deliverables:**

- [x] `src/csm/data/loader.py`
  - [x] `class DataAccessError(Exception)` — raised when `public_mode=True` (in `exceptions.py`)
  - [x] `TransientDataFetchError` — omitted (plan marks as optional; see phase plan Design Decision §7)
  - [x] `class OHLCVLoader`
    - [x] `__init__(self, settings: Settings)` — stores settings, creates semaphore
    - [x] `async def fetch(symbol: str, interval: str, bars: int) -> pd.DataFrame`
      - [x] Raises `DataAccessError` immediately when `settings.public_mode=True`
      - [x] Calls `tvkit.OHLCV.get_historical_ohlcv(symbol, interval, bars)`
      - [x] Retries up to `settings.tvkit_retry_attempts` only on transient network / timeout / transport failures
      - [x] Does not retry validation errors, schema mismatches, bad symbol inputs, or programming errors
      - [x] Returns DataFrame with columns `open`, `high`, `low`, `close`, `volume` + `DatetimeIndex` (`Asia/Bangkok` — see phase plan Design Decision §1)
    - [x] `async def fetch_batch(symbols: list[str], interval: str, bars: int) -> dict[str, pd.DataFrame]`
      - [x] Raises `DataAccessError` immediately when `settings.public_mode=True`
      - [x] Runs concurrent `fetch()` calls under `asyncio.Semaphore(settings.tvkit_concurrency)`
      - [x] Logs per-symbol failures without crashing the batch
      - [x] Returns `{symbol: DataFrame}` for all successfully fetched symbols; failed symbols are absent from the dict
- [x] Unit test: mock tvkit; assert `fetch` returns DataFrame with correct columns and `DatetimeIndex`
- [x] Unit test: `DataAccessError` is raised by `fetch` when `public_mode=True` — no tvkit call is made
- [x] Unit test: `DataAccessError` is raised by `fetch_batch` when `public_mode=True`
- [x] Unit test: `fetch_batch` continues after one symbol raises — failed symbol absent from result
- [x] Unit test: retry logic — mock tvkit raising twice then succeeding; assert `fetch` returns DataFrame after third attempt
- [ ] Integration smoke test (skipped in CI, manual only): `fetch("SET:SET", "1D", 100)` returns 100 rows

**Output DataFrame schema:**

| Column | dtype | Description |
|---|---|---|
| `open` | `float64` | Opening price (THB) |
| `high` | `float64` | Intraday high |
| `low` | `float64` | Intraday low |
| `close` | `float64` | Closing price |
| `volume` | `float64` | Shares traded |

Index: `DatetimeIndex`, name `"datetime"`, timezone `UTC`.

---

### Phase 1.4 — Universe Builder

**Status:** `[x]` Complete — 2026-04-22
**Plan:** `docs/plans/phase1_data_pipeline/phase1.4-universe-builder.md`

**Goal:** Define the investable universe deterministically. Produce both a full candidate list and dated per-rebalance snapshots that downstream backtesting can use without survivorship bias.

**Deliverables:**

- [x] `data/universe/symbols.json` — full SET symbol list sourced from `settfex` (PyPI) via `get_stock_list()` + `filter_by_market("SET")`
  - [x] Format: `{"symbols": ["SET:AAV", "SET:ADVANC", ...]}` — sorted, canonical tvkit format
  - [x] Atomic write (tmp file + rename) in `scripts/build_universe.py`
- [x] `src/csm/data/universe.py` — `UniverseBuilder`
  - [x] `__init__(self, store: ParquetStore, settings: Settings)`
  - [x] `def filter(self, symbol: str, asof: pd.Timestamp) -> bool`
    - [x] Price filter: latest close ≥ `MIN_PRICE_THB`
    - [x] Volume filter: 90-day trailing avg volume ≥ `MIN_AVG_DAILY_VOLUME`
    - [x] Coverage filter: valid bars ≥ `MIN_DATA_COVERAGE` of trailing `min(len(history), LOOKBACK_YEARS * 252)` bars
    - [x] Returns `False` immediately when symbol not in store
  - [x] `def build_snapshot(self, asof: pd.Timestamp, symbols: list[str]) -> list[str]`
    - [x] Applies all filters as of `asof` date (uses only data up to `asof`, no look-ahead)
    - [x] Returns sorted list of symbols passing all filters
  - [x] `def build_all_snapshots(self, symbols: list[str], rebalance_dates: pd.DatetimeIndex, snapshot_store: ParquetStore | None = None) -> None`
    - [x] Iterates rebalance dates, calls `build_snapshot`, saves to `ParquetStore`
    - [x] Key format: `universe/{YYYY-MM-DD}`; schema: `symbol` + `asof` columns
    - [x] Optional `snapshot_store` separates OHLCV source from universe output
- [x] Unit test: price filter rejects symbol with close < 1.0 THB
- [x] Unit test: volume filter rejects symbol below liquidity threshold
- [x] Unit test: coverage filter rejects symbol with > 20% missing bars
- [x] Unit test: `filter` returns `False` for symbol not in store
- [x] Unit test: `build_snapshot` uses only data `≤ asof` — no look-ahead leakage
- [x] Unit test: `build_all_snapshots` produces one snapshot per rebalance date

**Implementation notes:**

- Symbol source changed from `lumduan/thai-securities-data` to `settfex>=0.1.0` (PyPI) per user request; `settfex` added to `pyproject.toml`
- `_align_tz()` normalises `asof` to match store index timezone using `index.tz` directly (not the `TIMEZONE` constant) to be correct regardless of stored timezone
- Coverage denominator uses `history.tail(LOOKBACK_YEARS * 252)` as the window so numerator and denominator always match (prevents `coverage > 1.0` on long histories)
- `Settings` stored in `__init__` for future extension; filter thresholds come from `constants.py` in this phase
- Pre-existing `test_regime` failure unrelated to Phase 1.4 and out of scope

---

### Phase 1.5 — Price Cleaner

**Status:** `[x]` Complete — 2026-04-22
**Plan:** `docs/plans/phase1_data_pipeline/phase1.5-price-cleaner.md`

**Goal:** Standardise raw OHLCV DataFrames so that all downstream signal calculations operate on clean, consistent data.

**Deliverables:**

- [x] `src/csm/data/cleaner.py` — `PriceCleaner`
  - [x] `def forward_fill_gaps(df: pd.DataFrame, max_gap_days: int = 5) -> pd.DataFrame`
    - [x] Forward-fills NaN close prices for gaps of ≤ `max_gap_days` consecutive trading days
    - [x] Gaps larger than `max_gap_days` are left as NaN (not filled)
  - [x] `def drop_low_coverage(df: pd.DataFrame, min_coverage: float = MIN_DATA_COVERAGE, window_years: int = 1) -> pd.DataFrame | None`
    - [x] Returns `None` if the symbol has > `(1 - min_coverage)` missing bars in any rolling year
    - [x] Returns cleaned DataFrame otherwise
  - [x] `def winsorise_returns(df: pd.DataFrame, lower: float = 0.01, upper: float = 0.99) -> pd.DataFrame`
    - [x] Computes daily returns from `close`
    - [x] Clips returns at `lower` / `upper` percentile
    - [x] Back-computes and replaces extreme `close` values
  - [x] `def clean(df: pd.DataFrame) -> pd.DataFrame | None`
    - [x] Applies: `forward_fill_gaps` → `drop_low_coverage` → `winsorise_returns` in that order
    - [x] Returns `None` if the symbol is dropped by `drop_low_coverage`
- [x] Unit test: `forward_fill_gaps` fills a 3-day gap; leaves last day of a 6-day gap unfilled
- [x] Unit test: `drop_low_coverage` returns `None` for a symbol with 25% missing in one year
- [x] Unit test: `drop_low_coverage` returns DataFrame for a symbol with 15% missing
- [x] Unit test: `winsorise_returns` clips extreme return outliers to percentile bounds
- [x] Unit test: `clean` returns `None` when symbol fails coverage check
- [x] Unit test: `clean` applies all steps in correct order

**Implementation notes:**

- Existing wide-matrix API replaced with per-symbol OHLCV API (one DataFrame per symbol)
- `compute_returns` removed — not in Phase 1.5 spec; log-return reconstruction replaced with
  arithmetic pct_change for clarity and correctness of back-computed close values
- `drop_low_coverage` short-history guard: if `len(df) < window_years * 252`, checks full-series
  coverage instead of rolling window to avoid incorrectly dropping partially-populated stores
- `forward_fill_gaps` applies `ffill(limit=max_gap_days)` to all OHLCV columns (not just close)
  to keep rows internally consistent for suspended-trading gaps
- Only `close` column is modified by `winsorise_returns`; open/high/low/volume are unchanged

---

### Phase 1.6 — Bulk Fetch Script

**Status:** `[x]` Complete — 2026-04-22
**Plan:** `docs/plans/phase1_data_pipeline/phase1.6-bulk-fetch-script.md`

**Goal:** Provide a single idempotent entry point that fetches 20 years of daily history for all universe symbols and writes them to `data/raw/`.

**Deliverables:**

- [x] `scripts/fetch_history.py`
  - [x] Reads `data/universe/symbols.json` for the candidate symbol list; exits 1 if missing, malformed, or empty
  - [x] Initialises `OHLCVLoader` and `ParquetStore(data/raw/)`
  - [x] Skips symbols where `store.exists(symbol)` is already `True` (idempotent)
  - [x] Fetches in batches using `OHLCVLoader.fetch_batch()` with concurrency from `Settings`
  - [x] Saves each successfully fetched DataFrame via `ParquetStore.save()`; `StoreError` counted as failure
  - [x] Logs progress: symbols attempted / succeeded / failed
  - [x] Exits 1 if failure rate > `--failure-threshold` (default 0.1); configurable at CLI
  - [x] Writes `data/raw/fetch_failures.json` on failure; deletes stale file on zero-failure success
  - [x] Exits 1 immediately when `Settings.public_mode=True`
- [x] Unit tests: `tests/unit/scripts/test_fetch_history.py` — 18 tests, all passing
- [ ] Run script manually; verify `data/raw/` populated with ≥ 400 parquet files
- [ ] Re-run script; verify no symbols are re-fetched (idempotent check)

**Implementation notes:**

- `_SymbolsFile(BaseModel)` with `symbols: list[StrictStr]` — Pydantic strict validation rejects non-list and non-string elements
- Store key passed as raw symbol string (e.g. `"SET:AOT"`); `ParquetStore` applies `urllib.parse.quote` internally — no pre-encoding in this script
- All file I/O wrapped with `asyncio.to_thread()` for async compliance; `store.exists()` kept synchronous (simple `path.is_file()`, matches `build_universe.py` pattern)
- CLI validated at parse time: `_positive_int()` and `_unit_float()` type converters produce exit code 2 for out-of-range values
- `raw_dir.mkdir(parents=True, exist_ok=True)` called explicitly at startup, before `ParquetStore` init, to guarantee the failures file path exists
- `run_timestamp` captured at `main()` entry and embedded in `fetch_failures.json` for auditability
- `importlib.util.spec_from_file_location` used in tests to bypass pytest package namespace collision with `tests/unit/scripts/` directory

**Usage:**

```bash
# Activate environment and set credentials
uv sync --all-groups
cp .env.example .env
# Edit .env: set CSM_PUBLIC_MODE=false, tvkit browser session credentials

uv run python scripts/fetch_history.py
# Expected output:
# Found 412 symbols in universe
# Skipping 0 already-fetched symbols
# Fetching 412 symbols...
# Completed: 410 succeeded, 2 failed
# Failed symbols logged to data/raw/fetch_failures.json
```

---

### Phase 1.7 — Data Quality Check

**Status:** `[x]` Complete — 2026-04-23
**Plan:** `docs/plans/phase1_data_pipeline/phase1.7-data-quality-check.md`

**Goal:** Human sign-off that the raw data is fit for signal research. The notebook is the Phase 1 exit gate.

**Deliverables:**

- [x] `notebooks/01_data_exploration.ipynb`
  - [x] **Missing data heatmap** — symbols × years, colour = fraction missing; identify systematic gaps
  - [x] **Annual cross-sectional return distribution** — per-symbol annual return (year-end/year-start close − 1); box-plot distribution across symbols per year; flag extreme outliers
  - [x] **Liquidity distribution** — histogram of avg daily turnover (THB); annotate `MIN_AVG_DAILY_VOLUME` threshold
  - [x] **Survivorship bias / fetch completeness audit** — compare `symbols.json` vs raw store; top-10 symbols by calendar history length; limitation documented (not a full delisting audit)
  - [x] **Universe size over time** — symbols passing all Phase 1.4 filters per rebalance date (loaded from dated snapshots); target ≥ 400 at recent dates
  - [x] **Data coverage summary** — % of universe bucketed by literal calendar history length: ≥ 15Y, 10–15Y, < 10Y
  - [x] Final sign-off cell: print PASS/FAIL for all 6 exit criteria using imported constants

**Implementation notes:**

- Annual returns are cross-sectional (one scalar per symbol per year), not daily return time-series grouped by year
- Coverage denominator is `min(total_bars, LOOKBACK_YEARS × 252)` — consistent with `UniverseBuilder.filter()`
- Coverage summary Section 6 buckets by literal calendar history length (`(last − first).days / 365.25`), not bar count, to avoid mislabeling
- Universe snapshot keys: `universe_store = ParquetStore(data/universe/)`; keys are `"universe/{YYYY-MM-DD}"` (file path: `data/universe/universe/{YYYY-MM-DD}.parquet`)
- All markdown cells written in Thai per project convention
- Notebook gracefully handles empty `data/raw/` with `⚠ DATA NOT AVAILABLE` guards per section
- Pre-existing format violations in `src/csm/data/__init__.py` and `src/csm/data/exceptions.py` (missing trailing newline) fixed as part of this commit
- Pre-existing failures: 4 integration API tests and `test_regime_transitions_on_known_price_series` — unrelated to Phase 1.7; all 50 Phase 1 unit tests pass

---

## Data Models

### `Settings`

```python
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CSM_",
        env_file=".env",
        frozen=True,
    )

    public_mode: bool = False
    results_dir: Path = Path("./results")
    data_dir: Path = Path("./data")
    tvkit_concurrency: int = 5
    tvkit_retry_attempts: int = 3
    log_level: str = "INFO"
```

### OHLCV DataFrame Contract

All DataFrames passed between pipeline stages must conform to this schema. This is the approved internal exception to the general Pydantic-first rule: OHLCV history remains a DataFrame because the pipeline's storage, cleaning, and analytical operations are fundamentally columnar and vectorised. Validation still happens at the boundary by enforcing the schema below before data is persisted or handed to the next stage.

| Field | Type | Constraint |
|---|---|---|
| Index | `DatetimeIndex` | UTC, name = `"datetime"`, freq inferred |
| `open` | `float64` | > 0 |
| `high` | `float64` | ≥ `open`, ≥ `close` |
| `low` | `float64` | ≤ `open`, ≤ `close` |
| `close` | `float64` | > 0 |
| `volume` | `float64` | ≥ 0 |

### `DataAccessError`

```python
class DataAccessError(Exception):
    """
    Raised by OHLCVLoader when Settings.public_mode is True.

    In public mode the system has no tvkit credentials and must not
    attempt any live data fetch. Consumers should read from results/.
    """
```

---

## Error Handling Strategy

| Scenario | Behaviour |
|---|---|
| `public_mode=True` and fetch attempted | `DataAccessError` raised immediately; no network call |
| Single symbol fetch hits timeout, connection drop, or upstream transport failure | Retry up to `tvkit_retry_attempts`; log warning on each attempt |
| Single symbol fetch fails validation, receives malformed payload, or is called with bad input | Fail immediately; log error; no retry |
| Single symbol fetch fails after all retries | Log error; symbol absent from `fetch_batch` result; batch continues |
| Batch failure rate > 10% | `fetch_history.py` exits with non-zero status; partial results preserved |
| `ParquetStore.load` called for missing key | `KeyError` raised with descriptive message |
| `PriceCleaner.clean` drops symbol | Returns `None`; caller must check and skip |
| `UniverseBuilder.filter` called with no raw data for symbol | Returns `False` (symbol excluded from universe) |

Retryable failures must be limited to explicitly transient cases exposed by the async HTTP / WebSocket stack used by `tvkit` such as timeouts, connection resets, or temporary upstream unavailability. Non-retryable failures include schema validation failures, symbol-format errors, impossible OHLCV invariants, and other defects that require code or input correction.

### Logging Convention

All pipeline components use Python's standard `logging` module with logger names matching the module path (e.g. `csm.data.loader`). Log level is driven by `Settings.log_level`. Scripts configure `basicConfig` at startup; library code never calls `basicConfig`.

---

## Testing Strategy

### Coverage Target

Minimum 90% line coverage across `src/csm/` for Phase 1 changes, with 100% coverage expected for new public APIs introduced in this phase. Phase 1 unit tests should cover all branches in the storage layer and cleaner; the loader's async paths require mocking tvkit.

### Mocking Strategy

- `OHLCVLoader` tests: mock `tvkit.OHLCV.get_historical_ohlcv` with `unittest.mock.AsyncMock`
- `ParquetStore` tests: use `tmp_path` pytest fixture for isolated temp directories
- `UniverseBuilder` tests: use synthetic DataFrames with known properties
- `PriceCleaner` tests: construct DataFrames with deliberate gaps/outliers

### Test File Map

| Module | Test file |
|---|---|
| `src/csm/config/settings.py` | `tests/config/test_settings.py` |
| `src/csm/data/store.py` | `tests/data/test_store.py` |
| `src/csm/data/loader.py` | `tests/data/test_loader.py` |
| `src/csm/data/universe.py` | `tests/data/test_universe.py` |
| `src/csm/data/cleaner.py` | `tests/data/test_cleaner.py` |

### Integration Tests

- Mark with `@pytest.mark.integration` and skip in CI via `pytest -m "not integration"`
- `tests/data/test_loader_integration.py` — live fetch of `SET:SET` 1D 100 bars (requires credentials)

---

## Success Criteria

| Criterion | Measure |
|---|---|
| Clean parquet for ≥ 400 SET symbols | `len(store.list_keys())` in `data/raw/` |
| ≥ 15 years daily history for index | `SET:SET` parquet spans 2009-01-01 to present |
| Pipeline is idempotent | Re-running `fetch_history.py` fetches 0 new symbols |
| Public mode guard works | `DataAccessError` raised; no network call when `public_mode=True` |
| All unit tests pass | `uv run pytest tests/ -v -m "not integration"` exits 0 |
| Type checking clean | `uv run mypy src/` exits 0 |
| Linting clean | `uv run ruff check src/ scripts/` exits 0 |
| Data quality notebook signed off | All exit-criteria cells in `01_data_exploration.ipynb` print `PASS` |
| Universe ≥ 400 symbols at recent dates | `build_universe.py` log shows ≥ 400 symbols passing filters |
| No raw prices in `results/` | `.gitignore` excludes `data/`; only derived metrics in `results/` |

---

## Future Enhancements

- **Incremental daily refresh** — `OHLCVLoader.fetch_incremental(symbol)` fetches only bars since the last stored date; wired into the Phase 5 APScheduler daily job
- **Intraday data support** — Phase 9 adds `fetch(interval="1H")` for intraday entry timing signals
- **Symbol metadata store** — extend `data/universe/symbols.json` with sector, listing date, market cap band for richer universe filtering
- **Data validation schema** — `pandera` schema enforcement on every `ParquetStore.load` to catch schema drift

---

## Commit & PR Templates

### Commit Message (Plan — this commit)

```
plan(data-pipeline): add master plan for Phase 1 — Data Pipeline

- Creates docs/plans/Phase 1 — Data Pipeline/PLAN.md
- Covers seven sub-phases: Config, Storage, tvkit Loader, Universe Builder,
  Price Cleaner, Bulk Fetch Script, Data Quality Check
- Documents public_mode guard: DataAccessError raised on any fetch when
  CSM_PUBLIC_MODE=true
- Specifies OHLCV DataFrame schema contract shared across all pipeline stages
- Includes full architecture, data models, error handling, test matrix,
  and success criteria

Part of Phase 1 — Data Pipeline roadmap track.
```

### Commit Message (Implementation — Phase 1.1)

```
feat(config): add Settings and constants for data pipeline (Phase 1.1)

- Settings(BaseSettings) with CSM_ env prefix and .env binding
- public_mode flag: blocks data access when CSM_PUBLIC_MODE=true
- constants.py: INDEX_SYMBOL, SET_SECTOR_CODES, filter thresholds
- Unit tests: settings load from env, public_mode defaults to False
```

### Commit Message (Implementation — Phase 1.2)

```
feat(data): add ParquetStore storage layer (Phase 1.2)

- ParquetStore: save / load / exists / list_keys / delete
- Round-trip preserves DatetimeIndex (UTC) and all column dtypes
- Unit tests: 6 cases covering all public methods
```

### Commit Message (Implementation — Phase 1.3)

```
feat(data): add OHLCVLoader async tvkit wrapper (Phase 1.3)

- fetch() and fetch_batch() with concurrency semaphore and retry
- DataAccessError raised immediately when public_mode=True
- fetch_batch() continues after per-symbol failures
- Unit tests: mock tvkit, public_mode guard, retry, batch error isolation
```

### Commit Message (Implementation — Phase 1.4–1.5)

```
feat(data): add UniverseBuilder and PriceCleaner (Phases 1.4–1.5)

- UniverseBuilder: price / volume / coverage filters, dated snapshots
- PriceCleaner: forward-fill gaps, drop low-coverage, winsorise returns
- Unit tests: filter logic, no look-ahead leakage, cleaning order
```

### Commit Message (Implementation — Phase 1.6–1.7)

```
feat(scripts): add fetch_history.py and data quality notebook (Phases 1.6–1.7)

- fetch_history.py: idempotent 20-year bulk fetch for all universe symbols
- 01_data_exploration.ipynb: missing data heatmap, return distributions,
  liquidity distribution, survivorship audit, universe size over time
```

### PR Description Template

```markdown
## Summary

- Implements the complete data pipeline for csm-set (Phase 1 of 9)
- `Settings` (pydantic-settings) with `public_mode` guard — no live fetch when `CSM_PUBLIC_MODE=true`
- `ParquetStore` — typed save/load/exists/list for all pipeline artefacts
- `OHLCVLoader` — async tvkit wrapper with concurrency control, retry, and public mode enforcement
- `UniverseBuilder` — dated universe snapshots, survivorship-bias-safe
- `PriceCleaner` — gap-fill, coverage drop, returns winsorise
- `scripts/fetch_history.py` — idempotent 20-year bulk fetch
- `notebooks/01_data_exploration.ipynb` — data quality audit and phase sign-off

## Test plan

- [ ] `uv run pytest tests/ -v -m "not integration"` — all unit tests pass
- [ ] `uv run mypy src/` — exits 0
- [ ] `uv run ruff check src/ scripts/` — exits 0
- [ ] `uv run ruff format --check src/ scripts/` — no changes
- [ ] Manual: run `fetch_history.py` with valid credentials — verify ≥ 400 symbols fetched
- [ ] Manual: re-run `fetch_history.py` — verify 0 symbols re-fetched (idempotent)
- [ ] Manual: `CSM_PUBLIC_MODE=true uv run python scripts/fetch_history.py` — verify `DataAccessError` raised immediately
- [ ] Manual: open `01_data_exploration.ipynb`, run all cells, confirm all exit-criteria cells print `PASS`
```
