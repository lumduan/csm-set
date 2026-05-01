# Phase 6.3 — Export Results Script (Generic Data Contract)

**Feature:** Export results with JSON Schema sidecars for frontend-agnostic distribution
**Branch:** `feature/phase-6-docker`
**Created:** 2026-05-01
**Status:** Complete
**Completed:** 2026-05-01
**Depends on:** Phase 6.1 (Multi-stage Dockerfile — complete), Phase 6.2 (Docker Compose — complete)
**Positioning:** Owner-runnable script that produces the entire frontend-agnostic distribution payload — HTML notebooks, JSON metrics, and JSON Schema sidecars — under `results/static/`.

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

Phase 6.3 rewrites the existing `scripts/export_results.py` to produce a generic, type-safe, frontend-agnostic data contract under `results/static/`. Every output JSON carries `schema_version: "1.0"` and a sibling `<name>.schema.json` (JSON Schema draft-2020-12) so any client — React, Vue, Flutter, external notebook — can auto-generate types via `npx json-schema-to-typescript` without coupling to Python.

### Parent Plan Reference

- `docs/plans/phase_6_docker/PLAN.md` — Phase 6.3 section

### Key Deliverables

1. **`scripts/_export_models.py`** — Pydantic data contract models for all distribution payloads
2. **`scripts/export_results.py`** — Async exporter with CLI, Pydantic validation, schema sidecars
3. **`tests/integration/test_export_results.py`** — Idempotency, schema-match, notebook sanitization, resource logging
4. **`tests/unit/scripts/test_export_models.py`** — Pydantic model construction and schema generation

---

## AI Prompt

The following prompt was used to generate this phase:

```
🎯 Objective
Implement Phase 6.3 — Export Results Script (Generic Data Contract) for the csm-set project,
following the detailed plan in `docs/plans/phase_6_docker/PLAN.md`.

📋 Context
- Phase 6.1 and 6.2 are complete: multi-stage Dockerfile with HEALTHCHECK exists, CORS middleware
  is wired, docker-compose.yml and docker-compose.private.yml are configured.
- An existing export_results.py (110 lines) already runs notebooks, backtest, and signals export
  to results/{backtest,signals,notebooks}/ but lacks Pydantic data contract models, schema
  sidecars, argparse CLI, async function decomposition, and resource logging.
- Bug in existing code: CrossSectionalRanker().rank(feature_panel, latest_date) passes a
  Timestamp where rank() expects a string column name — must be fixed.
- Project standards: uv run for all commands, async-first I/O, Pydantic at boundaries, no
  secrets in repo, docs/plans/ is git-tracked, file size ≤ 400 lines.
- All requirements, data models, and acceptance criteria are specified in the Phase 6 master plan.

🔧 Requirements
1. Create scripts/_export_models.py with Pydantic models:
   - BacktestSummary, BacktestPeriod, BacktestConfigSnapshot, BacktestMetrics
   - EquityCurve/EquityPoint, AnnualReturns/AnnualRow
   - SignalRanking/RankingEntry, ExportResultsConfig
   - Each carries schema_version: Literal["1.0"]; none contain OHLCV fields

2. Rewrite scripts/export_results.py:
   - async def export_notebooks(config) with asyncio.create_subprocess_exec, 
     resource.getrusage memory logging, explicit timeout
   - async def export_backtest(config, backtest_config=None) with Pydantic validation
   - async def export_signals(config) with rank_all() fix + sector mapping
   - Schema sidecar emission: <name>.schema.json via Model.model_json_schema()
   - argparse CLI: --notebooks-only|--backtest-only|--signals-only|--skip-notebooks
   - Output to results/static/ (configurable via --output-dir)
   - Idempotent: sorted keys, indent=2, ensure_ascii=False

3. Add tests/integration/test_export_results.py:
   - test_backtest_idempotent: run twice, byte-identical except generated_at
   - test_schema_matches_data: validate each JSON against sibling schema
   - test_notebook_html_no_input: fixture notebook, assert code cells absent from HTML
   - test_resource_logging: peak memory log line appears after each notebook

4. Add tests/unit/scripts/test_export_models.py:
   - Pydantic model construction, default values, schema generation

5. Update docs/plans/phase_6_docker/PLAN.md Phase 6.3 status.

6. Quality gate: uv run ruff check . && uv run ruff format . && uv run mypy src/ scripts/ && uv run pytest tests/ -v
```

---

## Scope

### In Scope

| Component | Description | Status |
|---|---|---|
| `scripts/_export_models.py` | Pydantic data contract models with schema_version, field validation | Complete |
| `scripts/export_results.py` | Rewrite: async functions, Pydantic validation, schema sidecars, argparse CLI | Complete |
| `tests/integration/test_export_results.py` | Idempotency, schema match, notebook sanitization, resource logging | Complete |
| `tests/unit/scripts/test_export_models.py` | Model construction, defaults, schema generation | Complete |
| `docs/plans/phase_6_docker/PLAN.md` | Update Phase 6.3 status + completion notes | Complete |

### Out of Scope

- Updating API routers to read from `results/static/` (API currently reads from `results/{signals,backtest,notebooks}/` directly — Phase 6.4/6.6 concern)
- Phase 6.4 (data boundary audit): OHLCV leak detection via file walk + API response scan
- Phase 6.5 (README rewrite)
- Phase 6.6/6.7 (CI workflows)
- Docker Compose or Dockerfile changes

---

## Design Decisions

### 1. Output directory: `results/static/` (new tree, parallel to existing `results/{backtest,signals,notebooks}/`)

The spec mandates `results/static/` as the output root. The existing API routers read from `results/{signals,backtest,notebooks}/` directly — updating them to read from `results/static/` is deferred to Phase 6.4 (data boundary audit) where the path migration can be tested alongside the boundary checks. The `--output-dir` flag allows the owner to point at the old locations for backward compatibility.

### 2. Signal ranking fix: use `rank_all()` + extract latest date cross-section

The existing code `CrossSectionalRanker().rank(feature_panel, latest_date)` passes a `pd.Timestamp` where `rank()` expects a string column name (`"mom_12_1"`). This is a bug that would raise `ValueError`. Fix: use `rank_all(feature_panel)` to rank all numeric columns, then filter for the latest date's cross-section and extract `mom_12_1` values from the ranked result.

### 3. Backtest config injection for testability

`export_backtest()` accepts an optional `backtest_config: BacktestConfig | None = None` parameter. This allows tests with synthetic data (60 days, 3 symbols) to pass `BacktestConfig(formation_months=1, skip_months=0)` instead of the default `formation_months=12` which requires >12 months of data. The default parameter preserves backward compatibility — owners running the script with real data get the production defaults.

### 4. Pydantic validation before write

All JSON output is validated through the `scripts/_export_models.py` Pydantic models before writing to disk. This means:
- `BacktestResult.metrics_dict()` / `equity_curve_dict()` / `annual_returns_dict()` are NOT used directly — instead, we extract fields from `BacktestResult` and construct the canonical Pydantic models.
- The `SignalRanking` model enforces the exact schema (symbol, sector, quintile, z_score, rank_pct).
- If Pydantic validation fails, the script exits with an error before any file is written.

### 5. Async subprocess for nbconvert

Use `asyncio.create_subprocess_exec` instead of blocking `subprocess.run`. This allows the orchestrator to run notebooks concurrently if desired (future enhancement) and maintains the project's async-first I/O standard. Resource usage is logged via `resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss` after each notebook.

### 6. json.dumps with sort_keys for idempotency

Use `model.model_dump_json(indent=2)` for Pydantic model output (sorts keys by default). Schema files use `json.dumps(..., indent=2, sort_keys=True)`. The only field that changes between runs is `generated_at` in `BacktestSummary`.

### 7. `jsonschema` already available — no pyproject.toml change needed

`jsonschema` v4.26.0 is available as a transitive dependency of `nbconvert`. No modification to `pyproject.toml` is required.

---

## Implementation Steps

### Step 1: Create `scripts/_export_models.py`

Define all Pydantic models per the master plan spec:
- `BacktestPeriod(start: date, end: date)`
- `BacktestConfigSnapshot` — subset of BacktestConfig fields for reproducibility
- `BacktestMetrics` — cagr, sharpe, sortino, calmar, max_drawdown, win_rate, volatility (+ optional alpha, beta, information_ratio)
- `BacktestSummary` — schema_version, generated_at, backtest_period, config, metrics
- `EquityPoint` — date, nav, optional benchmark_nav
- `EquityCurve` — schema_version, description, series
- `AnnualRow` — year, portfolio_return, optional benchmark_return
- `AnnualReturns` — schema_version, rows
- `RankingEntry` — symbol, sector, quintile, z_score, rank_pct
- `SignalRanking` — schema_version, as_of, description, rankings
- `ExportResultsConfig` — notebook_dir, output_dir, execute, timeout_s, memory_budget_mb, only_notebooks, only_backtest, only_signals

### Step 2: Rewrite `scripts/export_results.py`

Replace the existing 110-line script with async functions:
- `_parse_args()` — argparse with mutex group
- `_write_json(path, model)` — sorted-key JSON via model_dump_json
- `_write_schema(path, model_class)` — JSON Schema via model_json_schema()
- `async def export_notebooks(config)` — nbconvert with subprocess, memory logging, timeout
- `async def export_backtest(config, backtest_config=None)` — load data, run backtest, validate through Pydantic, write JSON + schema
- `async def export_signals(config)` — rank_all, extract latest date, validate through Pydantic, write JSON + schema
- `async def main()` — orchestrator with CLI-driven skip logic
- `if __name__ == "__main__": asyncio.run(main())`

### Step 3: Create `tests/unit/scripts/test_export_models.py`

Pure Pydantic unit tests:
- Default values (schema_version, description)
- Field validation (quintile range, rank_pct range)
- Optional fields (benchmark_nav, benchmark_return, alpha/beta/information_ratio)
- Config defaults (output_dir, timeout_s)
- JSON Schema generation contains expected keys

### Step 4: Create `tests/integration/test_export_results.py`

Integration tests using `private_store` fixture:
- `test_backtest_idempotent` — run export_backtest twice, compare byte-for-byte except generated_at
- `test_signals_idempotent` — run export_signals twice, compare byte-for-byte
- `test_schema_matches_data` — validate each JSON against its sibling schema using jsonschema
- `test_notebook_html_no_input` — fixture .ipynb with code cell, run nbconvert, assert code absent from HTML
- `test_resource_logging` — assert peak memory log line after notebook export
- `test_public_mode_raises` — assert RuntimeError when public_mode is True
- `test_cli_flags` — assert --notebooks-only, --backtest-only, --signals-only, --skip-notebooks behavior

### Step 5: Update master plan

Mark Phase 6.3 deliverables as complete in `docs/plans/phase_6_docker/PLAN.md`. Add completion notes to this file.

### Step 6: Quality gate

```bash
uv run ruff check . && uv run ruff format . && uv run mypy src/ scripts/ && uv run pytest tests/ -v
```

---

## File Changes

| File | Action | Description |
|---|---|---|
| `scripts/_export_models.py` | CREATE | Pydantic data contract models (~120 lines) |
| `scripts/export_results.py` | REWRITE | Async exporter with Pydantic validation, schema sidecars, CLI (~250 lines) |
| `tests/unit/scripts/test_export_models.py` | CREATE | Model construction and schema generation tests (~80 lines) |
| `tests/integration/test_export_results.py` | CREATE | Idempotency, schema match, notebook sanitization tests (~180 lines) |
| `docs/plans/phase_6_docker/PLAN.md` | MODIFY | Update Phase 6.3 status + completion notes |
| `docs/plans/phase_6_docker/phase_6_3_export_results.md` | MODIFY | This file — completion notes |

---

## Success Criteria

- [ ] `scripts/_export_models.py` defines all 12 Pydantic models with `schema_version: "1.0"` and full field validation
- [ ] `scripts/export_results.py` exports notebooks → `results/static/notebooks/*.html`
- [ ] `scripts/export_results.py` exports backtest → `results/static/backtest/{summary,equity_curve,annual_returns}.json` + `.schema.json` siblings
- [ ] `scripts/export_results.py` exports signals → `results/static/signals/latest_ranking.json` + `.schema.json`
- [ ] All emitted JSONs validate against their sibling schemas (`jsonschema.validate`)
- [ ] Re-running produces byte-identical JSON except `generated_at` in summary
- [ ] `--notebooks-only`, `--backtest-only`, `--signals-only`, `--skip-notebooks` flags work correctly
- [ ] `--output-dir` flag allows custom output path
- [ ] Notebook HTML contains no code cell content (`--no-input` works)
- [ ] Resource logging shows peak memory after each notebook
- [ ] `uv run python scripts/export_results.py` exits 1 with clear message when `CSM_PUBLIC_MODE=true`
- [ ] `tests/unit/scripts/test_export_models.py` passes all model tests
- [ ] `tests/integration/test_export_results.py` passes all integration tests
- [ ] Quality gate green: ruff check, ruff format, mypy src/ scripts/, pytest all pass
- [ ] Coverage on `scripts/export_results.py` and `scripts/_export_models.py` ≥ 90%

---

## Completion Notes

### Summary

Phase 6.3 complete. The existing `scripts/export_results.py` was rewritten from a 110-line synchronous script into a ~360-line async-first exporter with Pydantic validation, JSON Schema sidecars, argparse CLI, and structured logging. A new `scripts/_export_models.py` (120 lines) defines 12 Pydantic data contract models — each with `schema_version: "1.0"` and strict field validation. Every output JSON now has a sibling `<name>.schema.json` sidecar for TypeScript type generation via `npx json-schema-to-typescript`.

The output directory defaults to `results/static/` (configurable via `--output-dir`), establishing the new frontend-agnostic data contract tree parallel to the existing `results/{backtest,signals,notebooks}/` structure that the API currently reads from.

### Key implementation details

- **Signal ranking bug fixed:** `CrossSectionalRanker().rank(feature_panel, latest_date)` (passing Timestamp where string expected) replaced with `rank_all(feature_panel)` + latest date cross-section extraction.
- **Backtest config injection:** `export_backtest()` accepts optional `backtest_config` parameter for testability with synthetic data.
- **Schema injection:** `_write_schema()` adds `$schema: "https://json-schema.org/draft/2020-12/schema"` to every emitted schema file for better tool compatibility.
- **36 new tests:** 19 model unit tests + 17 integration tests covering idempotency, schema-data co-validation, notebook HTML sanitization, resource logging, CLI flag parsing, public-mode guard, and missing-universe tolerance.

### Issues Encountered

1. **Namespace conflict with `tests.unit.scripts` package:** The `tests/unit/scripts/__init__.py` causes pytest to resolve `from scripts._export_models` relative to `tests.unit.scripts` during collection, resulting in `ModuleNotFoundError`. Both test files use `importlib.util.spec_from_file_location` to load `scripts._export_models` and `scripts.export_results` directly, bypassing the namespace issue.
2. **Pydantic `model_json_schema()` lacks `$schema` key:** Pydantic v2 does not include `$schema` in its JSON Schema output. Mitigated by injecting `schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")` in `_write_schema()`.

### Test Results

- **19/19** model unit tests pass
- **17/17** integration tests pass
- **753/753** total tests pass (no regressions)
- **ruff check / ruff format:** clean on all changed files
- **mypy src/ scripts/:** no new errors (one pre-existing error in `build_universe.py` unrelated)

---

**Document Version:** 1.1
**Author:** AI Agent
**Created:** 2026-05-01
**Status:** Complete
