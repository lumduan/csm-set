# Symbol Normalization Layer Implementation Plan

**Feature:** Canonical Symbol Formatting Across tvkit (`tvkit.symbols`)
**Branch:** `feature/symbol-normalization-layer`
**Created:** 2026-04-07
**Status:** Complete — All Phases (0–5) done — Released as v0.8.0
**Positioning:** Core data infrastructure — deterministic symbol identity across cache keys, storage paths, batch downloads, and validation systems

---

## Table of Contents

1. [Overview](#overview)
2. [Problem Statement](#problem-statement)
3. [Design Rationale](#design-rationale)
4. [Architecture](#architecture)
5. [API Design](#api-design)
6. [Implementation Phases](#implementation-phases)
7. [Data Models](#data-models)
8. [Error Handling Strategy](#error-handling-strategy)
9. [Testing Strategy](#testing-strategy)
10. [Success Criteria](#success-criteria)
11. [Future Enhancements](#future-enhancements)
12. [Issue Description](#issue-description)
13. [Commit & PR Templates](#commit--pr-templates)

---

## Overview

### Purpose

This feature implements a **symbol normalization layer** — `tvkit.symbols` — that resolves every TradingView instrument reference that carries explicit exchange information into a single canonical form: `EXCHANGE:SYMBOL` (uppercase, colon-separated). It is the first pillar of the Core Data Infrastructure roadmap track and a prerequisite for the Data Caching Layer and the Async Batch Downloader.

### Scope

**Phase 1 only handles symbols that already carry explicit exchange information.** Bare tickers (e.g. `AAPL` with no exchange prefix) and crypto slash-pairs (e.g. `BTC/USDT` requiring exchange inference) are out of scope for Phase 1. They are documented as future enhancements.

Phase 1 handles:

| Variant | Example | Canonical output |
|---|---|---|
| Colon, already canonical | `NASDAQ:AAPL` | `NASDAQ:AAPL` |
| Colon, lowercase | `nasdaq:aapl` | `NASDAQ:AAPL` |
| Dash notation | `NASDAQ-AAPL` | `NASDAQ:AAPL` |
| Dash notation, lowercase | `nasdaq-aapl` | `NASDAQ:AAPL` |
| Whitespace padding | `  NASDAQ:AAPL  ` | `NASDAQ:AAPL` |
| Crypto colon | `BINANCE:BTCUSDT` | `BINANCE:BTCUSDT` |
| Crypto colon, lowercase | `binance:btcusdt` | `BINANCE:BTCUSDT` |

Phase 1 does **not** handle (Phase 2+):

| Variant | Example | Status |
|---|---|---|
| Bare ticker | `AAPL` | Out of scope — Phase 2 |
| Slash crypto pair | `BTC/USDT` | Out of scope — Phase 2 |
| Bare crypto pair | `BTCUSDT` | Out of scope — Phase 2 |

### Normalization and Validation Ordering

A critical constraint for all Phase 3 integration work: **normalization must run before validation**. The existing pattern in `ohlcv.py` calls `validate_symbols` on the raw input, then calls `convert_symbol_format`. This means non-canonical inputs (e.g. lowercase) pass through an HTTP round-trip before format correction. The new ordering is:

```python
# ✅ Phase 3 target ordering — normalize first (no I/O), then validate
canonical: str = normalize_symbol(exchange_symbol)
await validate_symbols(canonical)
```

This ensures `validate_symbols` always receives a canonical `EXCHANGE:SYMBOL` string and that normalizable inputs (e.g. `nasdaq:aapl`) are accepted without errors.

---

## Problem Statement

TradingView instruments can appear in multiple string representations across user code, external data files, and environment variables:

```
NASDAQ:AAPL    (canonical)
nasdaq:aapl    (lowercase)
NASDAQ-AAPL    (dash notation)
  NASDAQ:AAPL  (whitespace padding)
```

Without a normalization layer:

- Cache keys diverge: `NASDAQ:AAPL` and `nasdaq:aapl` refer to the same instrument but hash differently
- Storage paths produced by `DataExporter` are inconsistent across pipelines
- Batch download deduplication fails silently when the same symbol appears in multiple formats
- Each consumer implements its own ad-hoc normalization, which fragments over time
- `validate_symbols` called on `nasdaq:aapl` may fail or produce unexpected results because the raw lowercased string reaches the HTTP endpoint before format correction

---

## Design Rationale

### Synchronous First

Symbol normalization is a pure-string transformation. Making it async would be misleading and would prevent its use in synchronous contexts (e.g., logging formatters, DataFrame column normalization, dict key construction). All Phase 1 functions are synchronous. Network-backed validation (`validate_symbols`) remains async and is a separate concern.

### Fail-Fast on Ambiguity

When a symbol is ambiguous — no exchange prefix and no `default_exchange` configured — `normalize_symbol` raises `SymbolNormalizationError` rather than silently guessing. Guessing produces wrong cache keys, which is harder to debug than an explicit error.

### No Additional Dependencies in Phase 1

`pydantic-settings` is a separate package from `pydantic` under Pydantic v2 and is not currently declared in `pyproject.toml`. Phase 1 uses a plain Pydantic `BaseModel` (not `BaseSettings`) for `NormalizationConfig`. There are no new runtime dependencies in Phase 1.

Environment variable support (`TVKIT_DEFAULT_EXCHANGE`) via `pydantic-settings` is deferred to Phase 2, which will explicitly add `pydantic-settings` to `pyproject.toml` as a dependency.

### Extend, Don't Replace

`convert_symbol_format` in `tvkit.api.utils` is kept for backward compatibility. `tvkit.symbols.normalize_symbol` is the new canonical entry point for all new code. In Phase 3, internal call sites are migrated and `convert_symbol_format` is deprecated with `warnings.warn`. `SymbolConversionResult` follows the same deprecation path since it is a public export. Both remain importable until the next major version.

### Zero Dependencies on Other tvkit Modules

`tvkit.symbols` must not import from `tvkit.api` to avoid circular imports. It is a leaf module.

---

## Architecture

### Module Structure

```
tvkit/
└── symbols/
    ├── __init__.py          # Public API: normalize_symbol, normalize_symbols,
    │                        #   normalize_symbol_detailed, NormalizedSymbol,
    │                        #   NormalizationConfig, NormalizationType,
    │                        #   SymbolNormalizationError
    ├── normalizer.py        # Core normalization logic
    ├── models.py            # Pydantic models: NormalizedSymbol, NormalizationConfig,
    │                        #   NormalizationType enum
    └── exceptions.py        # SymbolNormalizationError
```

### Dependency Graph

```
tvkit.symbols         (leaf — no tvkit imports)
    ↑ used by
tvkit.api.chart.ohlcv
tvkit.api.scanner.services.scanner_service
tvkit.export.DataExporter
```

### Relationship to Existing Code

**Before (current pattern in `ohlcv.py`):**

```
OHLCV.get_historical_ohlcv(exchange_symbol)
  1. await validate_symbols(exchange_symbol)   ← raw input, may fail on lowercase
  2. convert_symbol_format(exchange_symbol)    ← dash → colon only
```

**After (Phase 3 target):**

```
OHLCV.get_historical_ohlcv(exchange_symbol)
  1. normalize_symbol(exchange_symbol)         ← pure-string, zero I/O, comprehensive
  2. await validate_symbols(canonical)         ← always receives canonical form
```

---

## API Design

### Primary Entry Points

```python
from tvkit.symbols import normalize_symbol, normalize_symbols, SymbolNormalizationError

# Single symbol — returns canonical string directly
canonical: str = normalize_symbol("nasdaq:aapl")
# → "NASDAQ:AAPL"

canonical = normalize_symbol("NASDAQ-AAPL")
# → "NASDAQ:AAPL"

canonical = normalize_symbol("BINANCE:btcusdt")
# → "BINANCE:BTCUSDT"

# Batch normalization — 1:1 mapping, preserves input order, raises on first error
canonicals: list[str] = normalize_symbols(["NASDAQ:AAPL", "BINANCE:btcusdt"])
# → ["NASDAQ:AAPL", "BINANCE:BTCUSDT"]

# Ambiguous bare ticker — raises (Phase 2 adds default_exchange resolution)
try:
    normalize_symbol("AAPL")
except SymbolNormalizationError as exc:
    print(exc)  # "Cannot normalize 'AAPL': no exchange prefix"
```

### Detailed Result

`normalize_symbol` returns a plain `str` for ergonomics. A richer `NormalizedSymbol` model is available when metadata is needed:

```python
from tvkit.symbols import normalize_symbol_detailed, NormalizedSymbol

result: NormalizedSymbol = normalize_symbol_detailed("NASDAQ-AAPL")
print(result.canonical)          # "NASDAQ:AAPL"
print(result.exchange)           # "NASDAQ"
print(result.ticker)             # "AAPL"
print(result.original)           # "NASDAQ-AAPL"
print(result.normalization_type) # NormalizationType.DASH_TO_COLON
```

### Configuration Model (Phase 1 — no env-var support)

Phase 1 uses a plain Pydantic `BaseModel`, not `BaseSettings`. Environment variable support is added in Phase 2 when `pydantic-settings` is added as a dependency.

```python
from tvkit.symbols import NormalizationConfig

# Phase 1: explicit config only
config = NormalizationConfig(default_exchange="NASDAQ")
canonical = normalize_symbol("AAPL", config=config)
# → "NASDAQ:AAPL"  (Phase 2 feature — bare ticker via config)
```

> **Note:** `default_exchange` in `NormalizationConfig` and bare-ticker resolution are **Phase 2** features. The `NormalizationConfig` model ships in Phase 1 as a placeholder with `default_exchange=None` (which raises `SymbolNormalizationError` on bare tickers, same as the config-free path). Phase 2 activates the resolution logic and adds env var support.

---

## Implementation Phases

### Phase 0: Planning & Scaffolding

**Status:** Complete — 2026-04-07

**Tasks:**

- [x] Create branch: `feature/symbol-normalization-layer`
- [x] Add `docs/plans/symbol_normalization_layer/PLAN.md`
- [x] Create `tvkit/symbols/` package skeleton with empty modules
- [x] Add `docs/reference/symbols/normalizer.md` (completed in Phase 1)
- [x] Phase plan: `docs/plans/symbol_normalization_layer/phase0-planning-scaffolding.md`

---

### Phase 1: Core Normalization — Exchange-Aware Inputs Only

**Status:** Complete — 2026-04-07

**Goal:** Handle all symbol variants that already carry explicit exchange information. No network calls. No bare-ticker resolution.

**Deliverables:**

- [x] `tvkit/symbols/exceptions.py` — `SymbolNormalizationError`
- [x] `tvkit/symbols/models.py` — `NormalizedSymbol`, `NormalizationConfig` (BaseModel, no BaseSettings), `NormalizationType` enum
- [x] `tvkit/symbols/normalizer.py` — `normalize_symbol()`, `normalize_symbols()`, `normalize_symbol_detailed()`
- [x] `tvkit/symbols/__init__.py` — Public re-exports
- [x] `tests/test_symbols_normalizer.py` — 73 tests, 100% line + branch coverage
- [x] `docs/reference/symbols/normalizer.md` — API reference
- [x] Phase plan: `docs/plans/symbol_normalization_layer/phase1-core-normalization.md`

**Implementation notes (2026-04-07):**

1. **Validation regex broadened** — The plan specified `^[A-Z0-9]+:[A-Z0-9]+$`. Upon review of
   existing tvkit symbol usage (`FX_IDC:EURUSD` in `tvkit/quickstart.py`, futures like `CME_MINI:ES1!`,
   `NYSE:BRK.B`), the regex was broadened to `^[A-Z0-9_]+:[A-Z0-9._!]+$` to support underscores in
   exchange names and dots/exclamation marks in ticker components.

2. **`normalize_symbols` container validation** — Added a `isinstance(symbols, list)` guard that raises
   `SymbolNormalizationError` when a plain `str` is passed, preventing silent character-by-character
   iteration.

3. **Whitespace error message refinement** — `"INVALID SYMBOL"` (internal whitespace) and
   `" NASDAQ:AAPL "` with `strip_whitespace=False` (leading/trailing whitespace) now produce distinct
   error messages. The check for internal whitespace was moved above the "no exchange prefix" branch
   in the validation logic.

4. **`NormalizationConfig` remains `BaseModel`** — No new dependencies added in Phase 1. This is a
   documented temporary deviation from the project's Pydantic Settings requirement. Phase 2 upgrades
   to `BaseSettings` when `pydantic-settings` is added.

**Normalization Rules (applied in order):**

1. Strip leading/trailing whitespace (if `strip_whitespace=True`, default)
2. Raise `SymbolNormalizationError` if string is empty after step 1
3. Uppercase the entire string
4. If no `:` present and exactly one `-` present: replace first `-` with `:`
5. Validate the resulting string matches `^[A-Z0-9]+:[A-Z0-9]+$` — if not, raise `SymbolNormalizationError`
6. Return canonical string

**Input → Output mapping:**

| Input | Rule Applied | Output |
|---|---|---|
| `"nasdaq:aapl"` | Uppercase | `"NASDAQ:AAPL"` |
| `"NASDAQ-AAPL"` | Dash → colon, uppercase | `"NASDAQ:AAPL"` |
| `"nasdaq-aapl"` | Dash → colon, uppercase | `"NASDAQ:AAPL"` |
| `"BINANCE:btcusdt"` | Uppercase | `"BINANCE:BTCUSDT"` |
| `"  NASDAQ:AAPL  "` | Strip whitespace | `"NASDAQ:AAPL"` |
| `"AAPL"` | No exchange prefix | `SymbolNormalizationError` |
| `""` | Empty | `SymbolNormalizationError` |
| `"INVALID SYMBOL"` | Space in string | `SymbolNormalizationError` |
| `"A:B:C"` | Multiple colons | `SymbolNormalizationError` |

---

### Phase 2: Default Exchange & Env Var Support

**Status:** Complete — 2026-04-07

**Goal:** Allow bare tickers to be resolved via a configured `default_exchange`. Add `pydantic-settings` dependency for `TVKIT_DEFAULT_EXCHANGE` env var support.

**Deliverables:**

- [x] Add `pydantic-settings>=2.0.0` to `pyproject.toml` dependencies
- [x] Convert `NormalizationConfig` from `BaseModel` to `BaseSettings` with `env_prefix="TVKIT_"`
- [x] Activate bare-ticker resolution logic in `_normalize_core` when `config.default_exchange` is set
- [x] `examples/symbol_normalization_example.py` — shows env var usage
- [x] `tests/test_symbols_config.py` — 20 tests covering config-based resolution and `TVKIT_DEFAULT_EXCHANGE`
- [x] Updated `docs/reference/symbols/normalizer.md` — Phase 2 behaviour documented
- [x] Phase plan: `docs/plans/symbol_normalization_layer/phase2-default-exchange-envvar.md`

**API (Phase 2):**

```python
# Via config object
config = NormalizationConfig(default_exchange="NASDAQ")
normalize_symbol("AAPL", config=config)
# → "NASDAQ:AAPL"

# Via environment variable TVKIT_DEFAULT_EXCHANGE=NASDAQ
config = NormalizationConfig()   # reads from env lazily at construction time
normalize_symbol("AAPL", config=config)
# → "NASDAQ:AAPL"
```

**Implementation notes (2026-04-07):**

1. **Lazy instantiation replaces import-time singleton** — The Phase 1 `_DEFAULT_CONFIG` module-level
   singleton has been removed. All three public functions now call `NormalizationConfig()` at invocation
   time when `config is None`. This ensures `TVKIT_DEFAULT_EXCHANGE` set before a call is always
   picked up, with no import-time ordering constraint.

2. **Bare-ticker detection condition** — The resolution branch fires when `":"` is absent AND `"-"` is
   absent AND `config.default_exchange` is not None. The `"-"` exclusion is intentional: dash-notation
   symbols (e.g. `NASDAQ-AAPL`) are exchange-aware and must not be treated as bare tickers.

3. **`NormalizationType.DEFAULT_EXCHANGE` priority** — Placed below `WHITESPACE_STRIP` but above
   `DASH_TO_COLON`. A bare ticker with leading whitespace (e.g. `"  AAPL  "`) records `WHITESPACE_STRIP`
   as the primary normalization type.

4. **`used_default_exchange` flag** — A local boolean alongside the existing `used_dash_conversion`
   flag in `_normalize_core`, keeping consistent structure.

5. **Bare ticker + lowercase** — `"aapl"` with `default_exchange="NASDAQ"` → prepend gives
   `"NASDAQ:aapl"` → uppercase gives `"NASDAQ:AAPL"`. Normalization type: `DEFAULT_EXCHANGE`.

6. **`SettingsConfigDict(frozen=True)`** — Confirmed valid: `pydantic-settings` `SettingsConfigDict`
   inherits from Pydantic's `ConfigDict`, so `frozen=True` is supported alongside `env_prefix`.

---

### Phase 3: Integration with Existing tvkit Modules

**Status:** Complete — 2026-04-08

**Goal:** Replace the `validate → convert` call pattern in public API methods with `normalize → validate`.

**Current pattern (all six call sites in `ohlcv.py` at lines 610, 828, 1053, 1287, 1379, 1418):**

```python
await validate_symbols(exchange_symbol)         # raw input, normalisation happens after
symbol_result = convert_symbol_format(exchange_symbol)
converted_symbol: str = symbol_result.converted_symbol
```

**Target pattern (Phase 3):**

```python
canonical: str = normalize_symbol(exchange_symbol)   # pure-string, zero I/O
await validate_symbols(canonical)                    # always receives canonical form
```

**Call sites to migrate:**

| File | Lines | Change |
|---|---|---|
| `tvkit/api/chart/ohlcv.py` | 610, 828, 1053, 1287, 1379, 1418 | Replace validate+convert with normalize+validate |

**Deprecation of public API surface:**

`convert_symbol_format` and `SymbolConversionResult` are both public exports today (`tvkit/api/utils/__init__.py` lines 33, 41, 52). Deprecation covers both:

```python
# tvkit/api/utils/symbol_validator.py
def convert_symbol_format(...) -> ...:
    import warnings
    warnings.warn(
        "convert_symbol_format is deprecated and will be removed in a future major version. "
        "Use tvkit.symbols.normalize_symbol instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    ...
```

```python
# tvkit/api/utils/models.py  — SymbolConversionResult
class SymbolConversionResult(BaseModel):
    """
    .. deprecated::
        Use tvkit.symbols.NormalizedSymbol instead.
        SymbolConversionResult will be removed in a future major version.
    """
    ...
```

**Deliverables:**

- [x] Migrated all six call sites in `ohlcv.py`
- [x] `warnings.warn(DeprecationWarning)` in `convert_symbol_format`
- [x] Deprecation docstring on `SymbolConversionResult`
- [x] `docs/development/migration-symbol-normalization.md` — migration guide for `convert_symbol_format` → `normalize_symbol` and `SymbolConversionResult` → `NormalizedSymbol`
- [x] `tests/test_ohlcv_symbol_integration.py` — integration tests for normalization ordering and deprecation warnings
- [x] Phase plan: `docs/plans/symbol_normalization_layer/phase3-integration-with-modules.md`

**Implementation notes (2026-04-08):**

1. **Six call sites migrated** — five single-symbol (`_fetch_range_bars`, `_fetch_count_bars`,
   `get_ohlcv`, `get_quote_data`, `get_ohlcv_raw`) and one multi-symbol (`get_latest_trade_info`).
   All `converted_symbol` local variables renamed to `canonical`; multi-symbol path uses
   `normalize_symbols` + `validate_symbols(list)`.

2. **Scanner service unchanged** — a codebase search confirmed no `convert_symbol_format` or
   `validate_symbols` call sites in `tvkit/api/scanner/`. Scanner symbols are passed directly as
   filter values to TradingView's API; client-side normalization was not applied there.

3. **`# type: ignore` comments removed** — the old pattern required type narrowing via
   `# type: ignore` on `.converted_symbol` access. `normalize_symbol` returns `str` directly,
   eliminating all type ignores at the migrated call sites.

4. **Error type clarification** — `SymbolNormalizationError` is now raised for format errors
   before any I/O. `ValueError` from `validate_symbols` still applies for well-formed symbols
   not found in TradingView. The migration guide covers this distinction.

5. **`DeprecationWarning` stacklevel=2** — warning points to the caller's code, following the
   standard Python convention.

---

### Phase 4: Documentation & Examples

**Status:** Complete — 2026-04-08

**Deliverables:**

- [x] `docs/reference/symbols/normalizer.md` — Phase scope table updated; Phase 3 items marked complete
- [x] `docs/concepts/symbols.md` — "Dash-to-Colon" section replaced with "Symbol Normalization" section; Validation paragraph updated to show normalize → validate ordering; See Also updated
- [x] `docs/guides/symbol-normalization.md` — New step-by-step workflow guide
- [x] `examples/symbol_normalization_example.py` — Extended with `phase3_ohlcv_integration_pattern()` demonstrating the normalize → validate pattern via `unittest.mock`
- [x] `CHANGELOG.md` — v0.8.0 entry: Added `tvkit.symbols`, Changed `OHLCV` call ordering, Deprecated `convert_symbol_format` and `SymbolConversionResult`
- [x] Phase plan: `docs/plans/symbol_normalization_layer/phase4-documentation-examples.md`

**Implementation notes (2026-04-08):**

1. **Example extended, not replaced** — `examples/symbol_normalization_example.py` (Phase 2)
   was extended with a `phase3_ohlcv_integration_pattern()` function rather than creating a
   second normalization example. The new function uses `unittest.mock.AsyncMock` to patch
   `validate_symbols`, keeping the example runnable without a live network connection.

2. **`docs/development/migration-symbol-normalization.md` unchanged** — Reviewed and confirmed
   that the migration guide (created in Phase 3) already reflects the final API, error type
   changes, and deprecation timeline. No Phase 4 edits were required.

3. **CHANGELOG version bump deferred** — `pyproject.toml` version remains `0.7.0`; the
   CHANGELOG `[0.8.0]` entry is authored now so Phase 5 only confirms rather than drafts the
   release notes.

4. **`docs/concepts/symbols.md`** — The pre-Phase 4 "Dash-to-Colon Automatic Conversion"
   section described `convert_symbol_format` behaviour implicitly. It has been replaced with
   a "Symbol Normalization" section that names `tvkit.symbols.normalize_symbol` explicitly
   and cross-links the reference doc and the new guide.

---

### Phase 5: Release Preparation

**Status:** Complete — 2026-04-08

**Goal:** Verify the branch is clean, all gates pass, deprecated APIs remain backward-compatible, and the feature is ready to merge and publish.

**Deliverables:**

- [x] Finalize `CHANGELOG.md` — confirm entry is complete, version-bumped, and follows existing format
- [x] Verify `docs/development/migration-symbol-normalization.md` is accurate and covers both `convert_symbol_format → normalize_symbol` and `SymbolConversionResult → NormalizedSymbol`
- [x] Run full quality gate:

  ```bash
  uv run ruff check . && uv run ruff format . && uv run mypy tvkit/
  ```

- [x] Run full test suite:

  ```bash
  uv run python -m pytest tests/ -v
  ```

- [x] Confirm deprecated APIs still importable with `DeprecationWarning` (not removed):

  ```python
  import warnings
  with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      from tvkit.api.utils import convert_symbol_format, SymbolConversionResult
      assert any(issubclass(warning.category, DeprecationWarning) for warning in w)
  ```

- [x] Prepare release notes — summarize user-facing changes, migration path, and new public API surface
- [x] Push feature branch to GitHub:

  ```bash
  git push origin feature/symbol-normalization-layer
  ```

- [x] Open pull request targeting `main` using the PR template in [Commit & PR Templates](#commit--pr-templates)

**Implementation notes (2026-04-08):**

1. **Version bump** — `pyproject.toml` updated from `0.7.0` → `0.8.0`.

2. **Quality gates — all clean on first run:**
   - `ruff check .` — All checks passed
   - `ruff format .` — 82 files left unchanged
   - `mypy tvkit/` — Success: no issues found in 55 source files
   - `pytest tests/ -v` — 763 passed, 2 skipped, 0 failed (34.33s)

3. **Backward compatibility confirmed** — `convert_symbol_format("NASDAQ-AAPL")` emits exactly one
   `DeprecationWarning` pointing callers to `tvkit.symbols.normalize_symbol`. `SymbolConversionResult`
   remains importable without removal.

4. **PyPI publication** — Package published to production PyPI as `tvkit==0.8.0` via `scripts/publish.sh`.

5. **Phase plan** — `docs/plans/symbol_normalization_layer/phase5-release-preparation.md` created with
   full prompt, scope, checklist, quality gate results, and completion notes.

---

## Data Models

### `NormalizationType` Enum

```python
from enum import Enum

class NormalizationType(str, Enum):
    ALREADY_CANONICAL = "already_canonical"   # NASDAQ:AAPL → NASDAQ:AAPL (only uppercased)
    DASH_TO_COLON     = "dash_to_colon"       # NASDAQ-AAPL → NASDAQ:AAPL
    UPPERCASE_ONLY    = "uppercase_only"      # nasdaq:aapl → NASDAQ:AAPL
    WHITESPACE_STRIP  = "whitespace_strip"    # "  NASDAQ:AAPL  " → NASDAQ:AAPL (+ uppercase)
    DEFAULT_EXCHANGE  = "default_exchange"    # AAPL + config → NASDAQ:AAPL (Phase 2)
```

### `NormalizedSymbol` Model

```python
class NormalizedSymbol(BaseModel):
    """Result model returned by normalize_symbol_detailed()."""

    model_config = ConfigDict(frozen=True)

    canonical: str = Field(
        description="Canonical TradingView symbol in EXCHANGE:SYMBOL format (uppercase)."
    )
    exchange: str = Field(
        description="Exchange component of the canonical symbol (e.g. 'NASDAQ')."
    )
    ticker: str = Field(
        description="Ticker component of the canonical symbol (e.g. 'AAPL')."
    )
    original: str = Field(
        description="Original input string before normalization."
    )
    normalization_type: NormalizationType = Field(
        description="Classification of transformation applied."
    )
```

### `NormalizationConfig` Model

**Phase 1** — plain `BaseModel`, no env var support:

```python
from pydantic import BaseModel, ConfigDict, Field

class NormalizationConfig(BaseModel):
    """Configuration for symbol normalization behavior."""

    model_config = ConfigDict(frozen=True)

    default_exchange: str | None = Field(
        default=None,
        description=(
            "Exchange to use when no prefix is present in the symbol (e.g. 'NASDAQ'). "
            "Phase 2: also readable from TVKIT_DEFAULT_EXCHANGE environment variable."
        ),
    )
    strip_whitespace: bool = Field(
        default=True,
        description="Whether to strip leading/trailing whitespace before normalization.",
    )
```

**Phase 2** — upgraded to `BaseSettings` with `pydantic-settings`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class NormalizationConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TVKIT_")
    default_exchange: str | None = Field(default=None, ...)
    strip_whitespace: bool = Field(default=True, ...)
```

---

## Error Handling Strategy

### `SymbolNormalizationError`

```python
class SymbolNormalizationError(ValueError):
    """
    Raised when a symbol string cannot be normalized to canonical EXCHANGE:SYMBOL form.

    Attributes:
        original: The original symbol string that failed normalization.
        reason: Human-readable explanation of why normalization failed.
    """

    def __init__(self, original: str, reason: str) -> None:
        self.original = original
        self.reason = reason
        super().__init__(f"Cannot normalize '{original}': {reason}")
```

### Error Conditions

| Condition | `reason` message |
|---|---|
| Empty string | `"symbol must not be empty"` |
| Whitespace-only string | `"symbol must not be empty after stripping whitespace"` |
| No exchange prefix and `default_exchange` is None | `"no exchange prefix"` |
| Multiple `:` separators | `"symbol contains multiple ':' separators"` |
| Symbol contains whitespace after stripping | `"symbol must not contain internal whitespace"` |
| Ticker component empty after normalization | `"ticker component must not be empty after normalization"` |
| Exchange component empty after normalization | `"exchange component must not be empty after normalization"` |
| Characters outside `[A-Z0-9]` in either component | `"symbol components must contain only uppercase letters and digits"` |

---

## Testing Strategy

### Coverage Target

100% line and branch coverage for `tvkit/symbols/`.

### Test File

`tests/test_symbols_normalizer.py`

### Test Categories

**Happy path — all Phase 1 normalization variants:**

```python
@pytest.mark.parametrize("input_sym,expected", [
    ("NASDAQ:AAPL",     "NASDAQ:AAPL"),    # already canonical
    ("nasdaq:aapl",     "NASDAQ:AAPL"),    # lowercase
    ("NASDAQ-AAPL",     "NASDAQ:AAPL"),    # dash notation
    ("nasdaq-aapl",     "NASDAQ:AAPL"),    # dash + lowercase
    ("BINANCE:BTCUSDT", "BINANCE:BTCUSDT"),
    ("binance:btcusdt", "BINANCE:BTCUSDT"),
    ("  NASDAQ:AAPL  ", "NASDAQ:AAPL"),    # whitespace padding
    ("INDEX:NDFI",      "INDEX:NDFI"),     # index symbol
    ("USI:PCC",         "USI:PCC"),        # macro indicator
    ("FOREXCOM:EURUSD", "FOREXCOM:EURUSD"),
])
def test_normalize_symbol_happy_path(input_sym, expected): ...
```

**Edge cases:**

```python
def test_normalize_symbol_single_character_ticker(): ...     # e.g., "NYSE:A"
def test_normalize_symbol_numeric_ticker(): ...              # e.g., "HKEX:700"
def test_normalize_symbol_long_exchange_name(): ...          # e.g., "FOREXCOM:EURUSD"
def test_normalize_symbols_empty_list_returns_empty(): ...
def test_normalize_symbols_preserves_input_order(): ...
def test_normalize_symbols_one_to_one_no_dedup(): ...        # duplicate inputs → duplicate outputs
```

**Error conditions:**

```python
def test_normalize_symbol_empty_string_raises(): ...
def test_normalize_symbol_whitespace_only_raises(): ...
def test_normalize_symbol_bare_ticker_no_config_raises(): ...
def test_normalize_symbol_multiple_colons_raises(): ...
def test_normalize_symbol_internal_whitespace_raises(): ...
def test_normalize_symbol_empty_exchange_component_raises(): ...
def test_normalize_symbol_empty_ticker_component_raises(): ...
def test_normalize_symbol_special_characters_raises(): ...
```

**`normalize_symbols` raises on first error:**

```python
def test_normalize_symbols_raises_on_first_invalid(): ...
# ["NASDAQ:AAPL", "INVALID"] → raises on second symbol
```

**Detailed model:**

```python
def test_normalize_symbol_detailed_dash_notation(): ...
def test_normalize_symbol_detailed_normalization_type(): ...
def test_normalize_symbol_detailed_exchange_ticker_split(): ...
def test_normalize_symbol_detailed_already_canonical(): ...
```

**Config model (Phase 2 tests, separate file `test_symbols_config.py`):**

```python
def test_normalize_symbol_bare_ticker_with_default_exchange(): ...
def test_normalization_config_env_var(monkeypatch): ...  # TVKIT_DEFAULT_EXCHANGE
def test_normalization_config_default_exchange_none_raises(): ...
```

---

## Success Criteria

| Criterion | Measure |
|---|---|
| All Phase 1 inputs normalize deterministically | 100% parametrized test pass rate |
| No I/O in Phase 1 | Zero network calls (no mocking required) |
| `SymbolNormalizationError` raised on all ambiguous inputs | All error-condition tests pass |
| `normalize_symbols` is 1:1 (no deduplication) | Verified by `test_normalize_symbols_one_to_one_no_dedup` |
| Test coverage | 100% line + branch for `tvkit/symbols/` |
| Type checking | `uv run mypy tvkit/symbols/` exits 0 |
| Linting | `uv run ruff check tvkit/symbols/` exits 0 |
| Phase 3 normalization ordering | `normalize_symbol` runs before `validate_symbols` in all six `ohlcv.py` call sites |
| Backward compatibility | `convert_symbol_format` and `SymbolConversionResult` remain importable with `DeprecationWarning` |
| API documented | `docs/reference/symbols/normalizer.md` complete |
| Migration guide published | `docs/development/migration-symbol-normalization.md` covers both deprecated symbols |

---

## Future Enhancements

- **Bare-ticker resolution via exchange registry** (Phase 2) — resolve `AAPL` to `NASDAQ:AAPL` via a bundled JSON registry; no network required
- **Crypto slash-pair normalization** (Phase 2) — `BTC/USDT` → `BINANCE:BTCUSDT` via configurable crypto exchange preference
- **Async batch normalization with validation** — combine `normalize_symbols` + `validate_symbols` into a single async pipeline for batch downloads
- **Symbol aliasing** — allow users to define custom aliases (`"apple"` → `"NASDAQ:AAPL"`) via config

---

## Issue Description

> The following is the GitHub issue description for this feature, prepared using the project's Feature Request template.

---

**Title:** `[Feature] Add tvkit.symbols — canonical symbol normalization layer`

**Labels:** `enhancement`

---

### Feature category

- [x] Chart / OHLCV API
- [ ] Scanner API
- [ ] WebSocket / streaming
- [ ] Data export / processing
- [ ] Documentation
- [x] Other — new `tvkit.symbols` module (Core Data Infrastructure)

---

### Problem statement

TradingView instruments can appear in multiple string representations: colon-separated canonical form (`NASDAQ:AAPL`), lowercase variants (`nasdaq:aapl`), dash-separated (`NASDAQ-AAPL`), and whitespace-padded inputs (`  NASDAQ:AAPL  `).

There is currently no single, authoritative function in tvkit that maps these representations to one canonical form. As a result:

- Cache keys diverge: `NASDAQ:AAPL` and `nasdaq:aapl` refer to the same instrument but hash differently, producing duplicate cache entries
- Batch download deduplication fails silently when the same symbol appears in mixed formats
- Storage paths created by `DataExporter` are inconsistent
- `validate_symbols` called with raw lowercase input (e.g. `nasdaq:aapl`) runs an HTTP round-trip on an un-normalized string; format correction currently happens only after network validation

The existing `convert_symbol_format` helper handles only dash → colon conversion, does not uppercase, is not a public API, and is called after validation rather than before it.

---

### Use case

I am building a multi-symbol historical data pipeline that:

1. Reads a watchlist containing symbols in mixed formats (`NASDAQ:AAPL`, `nasdaq-aapl`, `BINANCE:BTCUSDT`)
2. Fetches historical bars using `OHLCV.get_historical_ohlcv()`
3. Caches results on disk keyed by symbol
4. Exports to Parquet, partitioned by symbol

Without a normalization layer, step 3 produces duplicate cache entries for the same instrument when the same symbol appears in different formats. I currently work around this by applying my own uppercase + colon-replacement before every API call — but this is fragile and not reusable across projects.

---

### Proposed solution

Add a new public module `tvkit.symbols` with a `normalize_symbol()` function that accepts any exchange-aware symbol variant and returns the canonical `EXCHANGE:SYMBOL` string (uppercase, colon-separated).

```python
from tvkit.symbols import normalize_symbol, normalize_symbols, SymbolNormalizationError

# All of these return "NASDAQ:AAPL"
normalize_symbol("NASDAQ:AAPL")
normalize_symbol("nasdaq:aapl")
normalize_symbol("NASDAQ-AAPL")
normalize_symbol("  NASDAQ:AAPL  ")

# Batch normalization — 1:1, preserves order
normalize_symbols(["NASDAQ:AAPL", "BINANCE:btcusdt"])
# → ["NASDAQ:AAPL", "BINANCE:BTCUSDT"]

# Detailed result with metadata
from tvkit.symbols import normalize_symbol_detailed
result = normalize_symbol_detailed("NASDAQ-AAPL")
print(result.canonical)          # "NASDAQ:AAPL"
print(result.normalization_type) # NormalizationType.DASH_TO_COLON

# Ambiguous input raises a clear error
try:
    normalize_symbol("AAPL")   # no exchange prefix
except SymbolNormalizationError as exc:
    print(exc)  # "Cannot normalize 'AAPL': no exchange prefix"
```

The function is **synchronous** (pure string transformation, no I/O), so it can be used in both sync and async contexts — including DataFrame column normalization, logging formatters, and dict key construction.

Internally, all public OHLCV methods will be updated so that `normalize_symbol` runs **before** `validate_symbols`, ensuring the HTTP round-trip always receives a canonical string.

---

### Alternatives considered

**1. Continue with `convert_symbol_format`**
Only handles dash → colon. Does not uppercase. Does not handle whitespace. Not a public API. Called after validation, not before. Insufficient.

**2. Ad-hoc normalization per call site**
Already the status quo — produces inconsistent behavior and is the root cause of the problem this feature solves.

**3. Async normalization function**
Unnecessary for pure-string operations and would block use in synchronous contexts. Network-backed validation (`validate_symbols`) remains separate and async.

---

### TradingView reference (if applicable)

TradingView's canonical symbol format is used throughout their WebSocket protocol — all instrument references use `EXCHANGE:SYMBOL` (uppercase, colon-separated). Examples: `NASDAQ:AAPL`, `BINANCE:BTCUSDT`, `INDEX:NDFI`, `FOREXCOM:EURUSD`.

---

### Additional context

- This is the first item in the **Core Data Infrastructure** track on the tvkit roadmap (`docs/roadmap.md`)
- It is a prerequisite for the Data Caching Layer and the Async Batch Downloader (both planned)
- Phase 1 adds no new runtime dependencies — uses only `pydantic` (already declared)
- Phase 2 will add `pydantic-settings` to `pyproject.toml` for env var support (`TVKIT_DEFAULT_EXCHANGE`)
- The existing `convert_symbol_format` function and `SymbolConversionResult` model will be deprecated (not removed) once Phase 3 ships, preserving backward compatibility until the next major version
- Proposed module path: `tvkit/symbols/` with `__init__.py`, `normalizer.py`, `models.py`, `exceptions.py`

---

### Willingness to contribute

- [x] I am willing to submit a pull request for this feature
- [ ] I can help with testing and feedback, but not implementation
- [ ] I am requesting this feature only — I am not able to contribute code

---

## Commit & PR Templates

### Commit Message (Phase 0 — Plan)

```
plan(symbols): add master plan for symbol normalization layer

- Creates docs/plans/symbol_normalization_layer/PLAN.md
- Covers four implementation phases: core normalization, config + env vars,
  module integration (normalize-before-validate ordering), and documentation
- Documents normalization-before-validation ordering at all six ohlcv.py
  call sites (lines 610, 828, 1053, 1287, 1379, 1418)
- Specifies deprecation path for convert_symbol_format and SymbolConversionResult
- Includes full API design, data models, error strategy, test matrix,
  and GitHub issue description

Part of Core Data Infrastructure roadmap track.
```

### Commit Message (Phase 1 — Implementation)

```
feat(symbols): add tvkit.symbols normalization layer (Phase 1)

- New module tvkit/symbols/ with normalizer.py, models.py, exceptions.py
- normalize_symbol() converts any exchange-aware variant to EXCHANGE:SYMBOL
- normalize_symbols() is a 1:1 batch variant preserving input order
- normalize_symbol_detailed() returns NormalizedSymbol with metadata
- SymbolNormalizationError with original + reason attributes
- NormalizationConfig as plain BaseModel (no pydantic-settings dependency)
- 100% test coverage in tests/test_symbols_normalizer.py
- API reference at docs/reference/symbols/normalizer.md

Phase 1 scope: handles colon, dash, lowercase, whitespace variants only.
Bare-ticker and crypto-pair resolution are Phase 2.

Closes #<issue-number>
```

### PR Description Template

```markdown
## Summary

- Adds `tvkit.symbols` as a new public module for canonical symbol normalization
- `normalize_symbol()` accepts exchange-aware symbol variants → returns `EXCHANGE:SYMBOL`
- `normalize_symbols()` is 1:1 (no deduplication), preserves input order
- Zero I/O — pure string transformation, usable in both sync and async contexts
- `SymbolNormalizationError` with clear messages for ambiguous or invalid input
- No new runtime dependencies in Phase 1

## Test plan

- [ ] `uv run python -m pytest tests/test_symbols_normalizer.py -v` — all tests pass
- [ ] `uv run mypy tvkit/symbols/` — exits 0
- [ ] `uv run ruff check tvkit/symbols/` — exits 0
- [ ] `uv run ruff format tvkit/symbols/` — no changes
- [ ] Verify `from tvkit.symbols import normalize_symbol` works in a fresh session
- [ ] Verify `convert_symbol_format` still importable (backward compat, no DeprecationWarning yet — Phase 3)
```
