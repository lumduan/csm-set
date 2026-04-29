# Phase 1.7 — Data Quality Check

**Feature:** Data Pipeline — Data Quality Check Notebook
**Branch:** `feature/phase-1-data-pipeline`
**Created:** 2026-04-23
**Status:** Complete
**Completed:** 2026-04-23
**Depends On:** Phase 1.6 — Bulk Fetch Script (Complete)

> **Document type:** Combined plan + implementation report. Written before coding
> (plan sections), then updated after coding (completion notes, checked criteria).

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Gap Analysis](#gap-analysis)
5. [Design Decisions](#design-decisions)
6. [Notebook Structure](#notebook-structure)
7. [Exit Criteria Specification](#exit-criteria-specification)
8. [Implementation Steps](#implementation-steps)
9. [Verification Addendum](#verification-addendum)
10. [File Changes](#file-changes)
11. [Success Criteria](#success-criteria)
12. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 1.7 delivers `notebooks/01_data_exploration.ipynb` — the human-facing audit and sign-off
gate for the entire Phase 1 data pipeline. It reads from `data/raw/` (raw OHLCV parquet files
produced by `fetch_history.py`) and `data/universe/` (symbol list and dated snapshots produced
by `build_universe.py`), runs a suite of structured quality checks, visualises the results, and
prints a final `PASS` / `FAIL` verdict for each exit criterion.

The notebook is the **last step before Phase 2 (Signal Research) can begin**. No downstream
quantitative work should proceed unless all sign-off criteria print `PASS`.

### Parent Plan Reference

- `docs/plans/phase1_data_pipeline/PLAN.md` — Phase 1.7 section

### Key Deliverables

1. **`notebooks/01_data_exploration.ipynb`** — complete, runnable data quality audit notebook
   with seven sections: data inventory, missing data heatmap, annual cross-sectional return
   distributions, liquidity distribution, survivorship bias / fetch completeness audit, universe
   size over time, data coverage summary, and a final sign-off cell.

---

## AI Prompt

The following prompt was used to initiate this implementation phase:

```text
🎯 Objective
Implement Phase 1.7 — Data Quality Check for the CSM-SET project by following a plan-before-code
methodology. The process must include creating a detailed plan markdown file, updating
documentation with progress notes, and committing all changes upon completion.

📋 Context
- The CSM-SET project uses a rigorous phase-based workflow for its data pipeline.
- Each phase requires a detailed plan before any code is written.
- The last completed phase was Phase 1.6 — Bulk Fetch Script, documented in
  `docs/plans/phase1_data_pipeline/phase1.6-bulk-fetch-script.md`.
- The next phase is Phase 1.7 — Data Quality Check, as described in
  `docs/plans/phase1_data_pipeline/PLAN.md`.
- All documentation and planning must follow the format in `docs/plans/examples/phase1-sample.md`.
- The plan markdown file for this phase must include the full prompt used to initiate the phase.

🔧 Requirements
- Carefully read and understand both `docs/plans/phase1_data_pipeline/PLAN.md` (focus on
  Phase 1.7) and `docs/plans/phase1_data_pipeline/phase1.6-bulk-fetch-script.md` (for
  documentation and workflow reference).
- Before coding, create a detailed plan for Phase 1.7 in
  `docs/plans/phase1_data_pipeline/phase1.7-data-quality-check.md`, including:
  - Overview, scope, gap analysis, design decisions, implementation steps, verification, file
    changes, success criteria, completion notes, and the full prompt.
  - Follow the format in `docs/plans/examples/phase1-sample.md`.
- Only begin implementation after the plan is complete and documented.
- During and after implementation, update both `docs/plans/phase1_data_pipeline/PLAN.md` and
  `docs/plans/phase1_data_pipeline/phase1.7-data-quality-check.md` with progress notes,
  completion checkmarks, issues encountered, and completion dates.
- All code and documentation must strictly follow project architectural principles: type safety,
  async/await for I/O, Pydantic validation, comprehensive error handling, and full test coverage.
- When the phase is complete, commit all changes (including updated docs and code).

📁 Code Context
- `docs/plans/phase1_data_pipeline/PLAN.md` (master plan, phase status, and requirements)
- `docs/plans/phase1_data_pipeline/phase1.6-bulk-fetch-script.md` (last completed phase)
- `docs/plans/examples/phase1-sample.md` (format reference for plan and prompt inclusion)
- Target plan file: `docs/plans/phase1_data_pipeline/phase1.7-data-quality-check.md`
- All relevant code and test files to be created or modified as specified in the plan

✅ Expected Output
- A new plan markdown file at `docs/plans/phase1_data_pipeline/phase1.7-data-quality-check.md`
  that includes the full prompt and follows the required format.
- Implementation of the Data Quality Check and all related code/tests as specified in the plan.
- Updated `docs/plans/phase1_data_pipeline/PLAN.md` and
  `docs/plans/phase1_data_pipeline/phase1.7-data-quality-check.md` with progress notes,
  checkmarks, completion dates, and any issues encountered.
- All changes committed upon completion of the phase.
```

---

## Scope

### In Scope (Phase 1.7)

| Component | Description | Status |
| --- | --- | --- |
| Section 0: Setup | Imports, paths, `ParquetStore` init, data inventory count | Complete |
| Section 1: Missing data heatmap | Symbols × years colour = fraction missing; systematic gap identification | Complete |
| Section 2: Annual cross-sectional return distribution | Per-symbol annual return (year-end / year-start close − 1); box-plot distribution across symbols per year | Complete |
| Section 3: Liquidity distribution | Histogram of avg daily turnover (THB); annotate `MIN_AVG_DAILY_VOLUME` threshold | Complete |
| Section 4: Survivorship bias audit | Fetch completeness audit (universe JSON vs raw store); top-10 symbols by calendar history length | Complete |
| Section 5: Universe size over time | Symbol count passing Phase 1.4 filters per rebalance date (loaded from dated snapshots) | Complete |
| Section 6: Data coverage summary | % of universe bucketed by literal calendar history length: ≥ 15Y, 10–15Y, < 10Y | Complete |
| Section 7: Sign-off | PASS/FAIL verdict for all 6 exit criteria | Complete |
| Graceful no-data handling | Each section checks data availability; prints `⚠ DATA NOT AVAILABLE` and skips if store is empty | Complete |

### Out of Scope (Phase 1.7)

- Running `PriceCleaner` — cleaning is a separate step; this notebook audits raw pipeline output
- Computing or displaying any momentum signal (Phase 2)
- Automated CI check of the notebook (this is a human sign-off gate, not a unit test)
- Reading from `data/processed/` — audit targets `data/raw/` and `data/universe/`

---

## Gap Analysis

`notebooks/01_data_exploration.ipynb` already exists in the repository but is empty (zero-byte
file committed during project setup). This section records the full delta to reach the Phase 1.7
spec.

### Notebook gaps

| Item | Existing | Required by Phase 1.7 | Action |
| --- | --- | --- | --- |
| Section 0: Setup | Not present | Imports, `ParquetStore`, path resolution, symbol inventory | Implement |
| Section 1: Missing data heatmap | Not present | Symbols × years `imshow` heatmap (matplotlib) | Implement |
| Section 2: Return distribution | Not present | Annual cross-sectional return box plots (per-symbol annual return per year) | Implement |
| Section 3: Liquidity distribution | Not present | Histogram of avg daily turnover with `MIN_AVG_DAILY_VOLUME` annotation | Implement |
| Section 4: Survivorship bias audit | Not present | Fetch completeness audit + top-10 symbols by calendar history length | Implement |
| Section 5: Universe size over time | Not present | Time-series bar chart of universe snapshot sizes | Implement |
| Section 6: Coverage summary | Not present | Bucketed by literal calendar history length: ≥15Y, 10–15Y, <10Y | Implement |
| Section 7: Sign-off | Not present | PASS/FAIL verdict for all 6 exit criteria | Implement |
| Graceful no-data | Not present | Guard each section against an empty data store | Implement |

---

## Design Decisions

### 1. Cross-sectional annual return definition

"Annual cross-sectional return distribution" means: for each calendar year `Y`, compute one
scalar return per symbol — `(close at last trading day of Y) / (close at first trading day of Y) − 1`
— then plot the distribution of those returns across all symbols. This gives the cross-section
of annual returns at each point in time, not the time-series of daily returns within a year.

Symbols with fewer than 20 valid close bars in year `Y` are excluded from that year's
cross-section to avoid spurious returns from near-empty histories.

### 2. Data coverage denominator

Coverage fraction for symbol `s`:

```
valid_close_bars = close_series.notna().sum()
window           = min(len(close_series), LOOKBACK_YEARS * 252)
coverage(s)      = valid_close_bars / window
```

This is the same formula used by `UniverseBuilder.filter()` (Phase 1.4), making the sign-off
threshold directly comparable to the universe filter's `MIN_DATA_COVERAGE = 0.80`.

### 3. History length buckets use literal calendar years

Section 6 (coverage summary) buckets symbols by **literal calendar history length** — the
elapsed time from the symbol's first valid close to its last valid close — not by bar count.

```python
first_date = close_series.first_valid_index()
last_date  = close_series.last_valid_index()
history_years = (last_date - first_date).days / 365.25
```

Bucket thresholds:
- **≥ 15Y**: `history_years >= 15` — full lookback window available
- **10–15Y**: `10 <= history_years < 15` — partial history
- **< 10Y**: `history_years < 10` — short history

This avoids mislabeling: a symbol fetched with 3 780 bars but spanning only 12 calendar years
(e.g. due to halted trading periods) will correctly land in the 10–15Y bucket.

### 4. Matplotlib only — no seaborn dependency

`seaborn` is not in `pyproject.toml`. All visualisations use `matplotlib` and pandas plotting
utilities (`.plot()`, `ax.boxplot()`, etc.) from the `research` dependency group. No new
packages are required.

### 5. Graceful no-data mode

When `data/raw/` is empty or `data/universe/symbols.json` is missing, each section prints a
formatted `⚠ DATA NOT AVAILABLE` message and skips all computation. This allows the notebook
to be committed and version-controlled before `fetch_history.py` is executed with real tvkit
credentials.

### 6. Constants imported from `src/csm/config/constants.py`

The sign-off cell imports `MIN_AVG_DAILY_VOLUME`, `MIN_DATA_COVERAGE`, and `LOOKBACK_YEARS`
directly from the project's constants module. Any future threshold change is automatically
reflected without editing the notebook.

### 7. Survivorship bias audit — what it proves and what it does not

The survivorship bias audit in Section 4 is a **fetch completeness audit**, not a full proof
of survivorship-bias-safe backtesting.

- **What it shows:** `settfex.get_stock_list()` queries the SET API for the full stock
  registry, which includes historically listed symbols (including delisted names). Comparing
  `data/universe/symbols.json` (the fetched candidate list) against the symbols actually
  stored in `data/raw/` reveals which historically-known symbols have raw OHLCV data and
  which were not fetched successfully.

- **What survivorship-bias protection actually relies on:** The dated universe snapshots
  produced by `build_universe.py`. Each snapshot contains only the symbols that passed
  price/volume/coverage filters *as of a given rebalance date*, using only data available
  up to that date (no look-ahead). This dated snapshot mechanism is the architectural
  guarantee against survivorship bias in downstream backtesting. It is implemented in
  `UniverseBuilder.filter()` and verified by the Phase 1.4 unit tests.

- **Limitation documented in notebook:** The Section 4 markdown cell explicitly states that
  showing "top-10 symbols by history length" is a proxy for earliest-listed symbols, not a
  definitive list of historically delisted stocks. True delisting metadata (listing date,
  suspension date, delisting date) is not available from `settfex` in Phase 1.

### 8. Universe snapshot key format

`build_universe.py` initialises `universe_store = ParquetStore(data_dir / "universe")` and
saves snapshots with key `f"universe/{date.strftime('%Y-%m-%d')}"`. The resulting on-disk
path is `data/universe/universe/{YYYY-MM-DD}.parquet`.

The notebook uses the same store base directory and filters listed keys:

```python
universe_store = ParquetStore(settings.data_dir / "universe")
snapshot_keys = [k for k in universe_store.list_keys() if k.startswith("universe/")]
```

Each snapshot is loaded via `universe_store.load(key)` where `key = "universe/YYYY-MM-DD"`.
This matches the `UniverseBuilder` implementation exactly.

### 9. Average daily turnover proxy

`avg_daily_turnover_thb = close.mean() × volume.mean()` (full-history simple average). This
is a rough proxy for THB liquidity and matches the spirit of the Phase 1.4 volume filter.
Rolling-windowed turnover analysis is deferred to Phase 2.

### 10. All markdown cells in Thai

Per project convention (`feedback_notebook_thai.md`), all markdown cells in `.ipynb` files
use Thai language. Code comments within code cells remain in English.

### 11. No notebook execution in CI

The notebook requires `data/raw/` to be populated by `fetch_history.py` with real tvkit
credentials before it can produce charts and sign-off verdicts. Execution is part of the
manual Phase 1 human sign-off, not a CI gate. Verification in this plan confirms only that
the notebook JSON is well-formed and that no regressions exist in existing unit tests and
static analysis.

---

## Notebook Structure

```
Cell 0:  [Markdown] ชื่อและวัตถุประสงค์ของ Notebook
Cell 1:  [Code]     Setup — imports, paths, stores, symbol inventory
Cell 2:  [Markdown] ส่วนที่ 1: Missing Data Heatmap
Cell 3:  [Code]     Missing data heatmap (symbols × years matrix)
Cell 4:  [Markdown] ส่วนที่ 2: การกระจายของผลตอบแทนรายปี (Cross-Sectional)
Cell 5:  [Code]     Annual cross-sectional return box plots
Cell 6:  [Markdown] ส่วนที่ 3: การกระจายของสภาพคล่อง
Cell 7:  [Code]     Liquidity distribution histogram
Cell 8:  [Markdown] ส่วนที่ 4: การตรวจสอบ Survivorship Bias / ความสมบูรณ์ของข้อมูล
Cell 9:  [Code]     Survivorship bias / fetch completeness audit
Cell 10: [Markdown] ส่วนที่ 5: ขนาด Universe ตามช่วงเวลา
Cell 11: [Code]     Universe size over time bar chart
Cell 12: [Markdown] ส่วนที่ 6: สรุปความครอบคลุมของข้อมูล
Cell 13: [Code]     Coverage summary table (calendar-year history length buckets)
Cell 14: [Markdown] ส่วนที่ 7: การตรวจสอบและอนุมัติ (Sign-off)
Cell 15: [Code]     Sign-off — PASS/FAIL for all 6 exit criteria
```

---

## Exit Criteria Specification

The sign-off cell (Cell 15) evaluates and prints `✓ PASS` or `✗ FAIL` for each criterion:

| # | Criterion | Threshold | Computation |
| --- | --- | --- | --- |
| 1 | Raw symbol count ≥ 400 | 400 | `len(raw_store.list_keys())` |
| 2 | Index history ≥ 15 years | `LOOKBACK_YEARS × 252` bars | Bar count for `SET:SET` in `data/raw/` |
| 3 | Median data coverage ≥ 80% | `MIN_DATA_COVERAGE = 0.80` | Median of `valid_bars / min(total_bars, LOOKBACK_YEARS×252)` across all symbols |
| 4 | Median avg daily turnover ≥ threshold | `MIN_AVG_DAILY_VOLUME` | Median of `close.mean() × volume.mean()` across all symbols |
| 5 | Universe snapshots present | ≥ 1 | `len([k for k in universe_store.list_keys() if k.startswith("universe/")])` |
| 6 | No symbol with 0 valid bars | 0 symbols | Count of symbols where `close.notna().sum() == 0` |

If any data store is empty, the corresponding criterion automatically prints `✗ FAIL (NO DATA)`.

---

## Implementation Steps

### Step 1: Write this plan document (complete before any code changes) ✓

### Step 2: Implement `notebooks/01_data_exploration.ipynb`

Build cells in order:

**Cell 1 — Setup:**
```python
import sys; sys.path.insert(0, "../src")
import json, warnings
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from csm.config.settings import Settings
from csm.config.constants import MIN_AVG_DAILY_VOLUME, MIN_DATA_COVERAGE, LOOKBACK_YEARS
from csm.data.store import ParquetStore

settings = Settings()
raw_store = ParquetStore(settings.data_dir / "raw")
universe_store = ParquetStore(settings.data_dir / "universe")
symbol_keys = raw_store.list_keys()
print(f"Raw symbols found: {len(symbol_keys)}")
```

**Cell 3 — Missing data heatmap:**
- For each symbol, load `close`, resample to annual frequency, compute fraction of NaN per
  year. Build a 2-D matrix `(symbols × years)`. Display via `plt.imshow` with `RdYlGn_r`
  colormap. Limit x-axis labels to sampled years for readability.

**Cell 5 — Annual cross-sectional return distribution:**
- For each symbol, group close by calendar year, take first and last valid close per year,
  compute `(last / first) - 1`. Exclude years with fewer than 20 valid bars.
- Build dict `{year: [returns_across_symbols]}`. Use `ax.boxplot` with one box per year.

**Cell 7 — Liquidity distribution:**
- For each symbol, compute `close.mean() × volume.mean()`. Plot `np.log10(turnover)`
  histogram. Add vertical line at `np.log10(MIN_AVG_DAILY_VOLUME)`.

**Cell 9 — Survivorship bias / fetch completeness audit:**
- Load `data/universe/symbols.json`. Compare `universe_candidates` vs `raw_store.list_keys()`.
- Print total candidates, fetched count, and missing count.
- Build per-symbol calendar history length. Show top-10 by history length.
- Include explicit note: this is a fetch completeness audit, not a delisting audit.

**Cell 11 — Universe size over time:**
- Load all keys `k in universe_store.list_keys()` where `k.startswith("universe/")`.
- For each key, load snapshot, count rows. Build `pd.Series({date_str: count})`.
- Plot as a vertical bar chart.

**Cell 13 — Coverage summary:**
- For each symbol, compute calendar history length:
  `(last_valid_date - first_valid_date).days / 365.25`.
- Bucket: ≥ 15Y, 10–15Y, < 10Y. Print count and % for each bucket.

**Cell 15 — Sign-off:**
- Evaluate all 6 criteria. Print `✓ PASS` or `✗ FAIL` for each.
- Print overall banner: `=== ALL CHECKS PASSED — PHASE 1 SIGN-OFF COMPLETE ===` or
  `=== SOME CHECKS FAILED — DO NOT PROCEED TO PHASE 2 ===`.

### Step 3: Update PLAN.md and this document; commit

---

## Verification Addendum

Run in this exact order:

```bash
# Confirm current branch and clean working tree
git status
git branch --show-current   # expected: feature/phase-1-data-pipeline

# Confirm notebook JSON is well-formed (structure check only — no execution)
uv run python -c "import json; json.load(open('notebooks/01_data_exploration.ipynb'))" \
  && echo "Notebook JSON: OK"

# Lint — src/ and scripts/ (notebooks excluded from ruff by default)
uv run ruff check src/ scripts/

# Format check
uv run ruff format --check src/ scripts/

# Type check — src/ only (notebooks not in mypy scope)
uv run mypy src/

# Full Phase 1 unit suite, excluding integration tests — confirm no regressions
uv run python -m pytest tests/ -v -m "not integration"
```

**Note on notebook execution:** The notebook is a human sign-off gate that requires
`data/raw/` to be populated by `fetch_history.py` with valid tvkit credentials. It is not
executed as part of the automated verification above. The no-data guards are verified by
code inspection; behaviour with live data is verified by the user as part of the manual
Phase 1 sign-off.

---

## File Changes

| File | Action | Description |
| --- | --- | --- |
| `notebooks/01_data_exploration.ipynb` | REWRITE | Full Phase 1.7 data quality audit notebook (was empty) |
| `docs/plans/phase1_data_pipeline/phase1.7-data-quality-check.md` | CREATE | This document |
| `docs/plans/phase1_data_pipeline/PLAN.md` | MODIFY | Phase 1.7 status + completion notes |

---

## Success Criteria

- [x] `notebooks/01_data_exploration.ipynb` has all 7 sections as specified in PLAN.md Phase 1.7
- [x] Section 2 computes annual cross-sectional returns (one scalar per symbol per year, not daily return time-series)
- [x] Coverage denominator is `min(total_bars, LOOKBACK_YEARS × 252)` — consistent with `UniverseBuilder.filter()`
- [x] Section 6 buckets by literal calendar history length (`history_years = (last − first).days / 365.25`), not bar count
- [x] Sign-off cell evaluates and prints PASS/FAIL for all 6 exit criteria using imported constants
- [x] Survivorship bias section includes explicit note that it is a fetch completeness audit, not a delisting audit
- [x] Universe size section loads snapshot keys via `universe_store.list_keys()` filtering on `"universe/"` prefix
- [x] All markdown cells written in Thai
- [x] No-data guards verified by code inspection (notebook not executed without real data; this is documented and expected)
- [x] `uv run python -c "import json; json.load(open('notebooks/01_data_exploration.ipynb'))"` exits 0
- [x] `uv run ruff check src/ scripts/` exits 0
- [x] `uv run ruff format --check src/ scripts/` exits 0
- [x] `uv run mypy src/` exits 0
- [x] `uv run python -m pytest tests/ -v -m "not integration"` — no new failures

---

## Completion Notes

### Summary

Phase 1.7 complete. `notebooks/01_data_exploration.ipynb` rewritten from empty file to full
Phase 1.7 spec: seven sections covering missing data heatmap, annual cross-sectional return
distribution (per-symbol annual return per year), liquidity distribution, survivorship bias /
fetch completeness audit with documented scope limitations, universe size over time (loaded
from dated snapshot parquets), data coverage summary (bucketed by literal calendar history
length ≥15Y / 10–15Y / <10Y), and a final sign-off cell with PASS/FAIL verdicts for all 6
exit criteria. All sections handle the no-data case gracefully. All markdown cells in Thai.
Notebook JSON well-formed. No regressions in mypy, ruff, or unit tests.

### Issues Encountered

1. **Universe snapshot key format includes directory prefix** — `build_universe.py` uses
   `ParquetStore(data_dir / "universe")` and key `"universe/{YYYY-MM-DD}"`. The on-disk
   path is `data/universe/universe/{YYYY-MM-DD}.parquet`. The notebook matches this by
   filtering `list_keys()` for keys starting with `"universe/"`.

2. **Empty data directory at implementation time** — `data/raw/` and `data/universe/` contain
   no parquet files (tvkit credentials not available). Notebook no-data behaviour was verified
   by code inspection only; execution with real data is the user's manual sign-off step.

3. **Survivorship bias claim limited to fetch completeness** — A full delisting audit would
   require per-symbol listing/delisting metadata not available from `settfex` in Phase 1.
   This limitation is documented explicitly in the Section 4 markdown cell.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Sonnet 4.6)
**Status:** Complete
**Completed:** 2026-04-23
