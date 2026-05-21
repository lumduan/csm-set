# Phase 1 — csm-set Metric Computations + Payload

**Feature:** `feature-strategies-report-metrics` — Phase 1 of 5 (csm-set portion).
**Sub-repo:** `strategies/csm-set` (own git repo, remote `lumduan/csm-set`).
**Branch:** `feature/strategy-report-metrics-phase1` (off `live-test`).
**Created:** 2026-05-21
**Status:** Complete
**Completed:** 2026-05-21
**Umbrella roadmap:** [`../../../../plans/feature-strategies-report-metrics/ROADMAP.md`](../../../../plans/feature-strategies-report-metrics/ROADMAP.md)

---

## Table of contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design decisions](#design-decisions)
5. [Implementation steps](#implementation-steps)
6. [File changes](#file-changes)
7. [Success criteria](#success-criteria)
8. [Progress notes](#progress-notes)
9. [Completion notes](#completion-notes)

---

## Overview

### Purpose

Phase 1 makes `csm-set` compute the TradingView-style per-strategy
report once per refresh and attach it to the existing gateway
write path under `extended_data.report`. It introduces the
`StrategyReport` Pydantic v2 model tree (gateway-schema-1:1), pure
trade-based metric helpers, run-up analysis, a deterministic FIFO
trade-pairing module, an offline-first benchmark loader, and a
read-only history endpoint that returns the latest persisted report.

### Parent plan reference

Umbrella ROADMAP (Phases 1–5):
[`plans/feature-strategies-report-metrics/ROADMAP.md`](../../../../plans/feature-strategies-report-metrics/ROADMAP.md).

### Key deliverables

| # | Deliverable | Status |
|---|---|---|
| 1 | `src/csm/research/strategy_report.py` + `strategy_report_models.py` | Complete |
| 2 | `src/csm/research/exceptions.py` extended with `ReportError` | Complete |
| 3 | `src/csm/risk/trade_metrics.py` — Decimal-typed trade metrics | Complete |
| 4 | `src/csm/risk/drawdown.py` extended with `runup_episodes` + derived stats | Complete |
| 5 | `src/csm/execution/trade_pairing.py` + `execution/errors.py` | Complete |
| 6 | `src/csm/data/benchmark.py` + `BenchmarkUnavailableError` | Complete |
| 7 | `src/csm/live/portfolio.py` `LivePortfolioMetrics.report` + `as_dict()` | Complete |
| 8 | `src/csm/adapters/hooks.py` builds report, replaces metrics, soft-skip trade write | Complete |
| 9 | `src/csm/adapters/gateway.py` payload-size + report-presence log line | Complete |
| 10 | `api/routers/history.py` adds `GET /api/v1/history/strategy-report` | Complete |
| 11 | `src/csm/config/settings.py` adds `CSM_BENCHMARK_SYMBOL` and `CSM_REPORT_ENABLE_PUBLIC` | Complete |
| 12 | Unit + integration tests covering all of the above | Complete |
| 13 | This plan + umbrella ROADMAP updates | Complete |

---

## AI Prompt

The verbatim prompt that drove this phase:

```
You are tasked with implementing Phase 1 — strategies/csm-set metric
computations + payload for the csm-set project. Follow these steps
precisely:

1. **Preparation**
   - Read `.claude/knowledge/project-skill.md` fully to internalize all
     engineering standards.
   - Read `.claude/playbooks/feature-development.md` fully to internalize
     the development workflow.
   - Read `../../plans/feature-strategies-report-metrics/ROADMAP.md`
     carefully. Focus exclusively on the Phase 1 section:
     "strategies/csm-set — metric computations + payload". Note all
     deliverables, acceptance criteria, and dependencies.

2. **Planning (mandatory before any code)**
   - Draft a detailed implementation plan in markdown using
     `docs/plans/examples/phase1-sample.md` as the format reference.
   - The plan must include: scope, deliverables, acceptance criteria,
     risks, implementation steps, and the full AI agent prompt (this
     prompt) embedded in the plan.
   - Save the plan as
     `docs/plans/feature-strategies-report-metrics/PLAN.md`.
   - Do NOT write any implementation code until this file is saved.

3. **Implementation**
   - Implement all Phase 1 deliverables as defined in the ROADMAP and
     your plan:
     - Metric computation functions (e.g., Sharpe, Sortino, max
       drawdown, hit rate, turnover, IC, or whatever Phase 1 specifies —
       follow the ROADMAP exactly).
     - Pydantic V2 payload models for metric results, suitable for API
       responses and results/static/ export.
     - Any required updates to existing src/csm/ subpackages (features,
       research, risk, portfolio, execution) to wire in the new
       metrics.
   - All code standards must be met:
     - `from __future__ import annotations` at top of every src/csm/
       module
     - Complete type annotations on all public functions and methods
     - Pydantic V2 models for all data structures crossing module
       boundaries
     - `logger = logging.getLogger(__name__)` — never `print()`; use
       `%`-style formatting
     - Module-local exceptions in `errors.py` inheriting from `CsmError`
     - Async/await for all I/O; `httpx.AsyncClient` for HTTP; no
       `requests`
     - File size ≤ 400 lines; functions ≤ ~50 lines
     - Import order: stdlib → third-party → local
     - Named parameters in all function calls
     - No raw OHLCV columns (`open`, `high`, `low`, `close`, `volume`,
       `adj_close`) in any payload or results/static/ output
   - Write unit tests in `tests/unit/` mirroring the src/csm/ structure:
     - Cover ≥ 90% of new code
     - Test edge cases: empty data, single-row frames, NaN values,
       zero-division, timezone boundary
     - Test error conditions and exception types
     - No real API calls in unit tests; mock external dependencies
     - Use `asyncio_mode = "auto"` and `--import-mode=importlib`

4. **Documentation and Progress Tracking**
   - After implementation and tests pass, update
     `docs/plans/feature-strategies-report-metrics/PLAN.md` with:
     - Progress notes for each deliverable
     - Completion date (today: May 21, 2026)
     - Any issues encountered during testing or implementation
     - Check marks on completed acceptance criteria
   - Update `../../plans/feature-strategies-report-metrics/ROADMAP.md`:
     - Mark Phase 1 items as completed with check marks
     - Add any notes on deviations or follow-up items

5. **Knowledge and Playbook Updates**
   - If any new patterns, conventions, or reusable knowledge emerged
     during implementation:
     - Create or update the appropriate file in `.claude/knowledge/` or
       `.claude/playbooks/`
     - Update `CLAUDE.md` to reference any new files or conventions

6. **Quality Gate (must pass before commit)**
   Run all of the following and fix any failures:
   ```bash
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy src/
   uv run pytest tests/ -v --cov=src/csm --cov-report=term-missing
   ```

7. **Commit**
   - Commit all changes (implementation, tests, docs, .claude/*
     updates) in a single commit.
   - Use Conventional Commits format with a clear scope, e.g.:
     `feat(metrics): implement Phase 1 metric computations + payload
     models`
   - Commit body should list all new/modified files with brief
     descriptions.

**Files to reference and/or modify:**
- .claude/knowledge/project-skill.md (read)
- .claude/playbooks/feature-development.md (read)
- ../../plans/feature-strategies-report-metrics/ROADMAP.md (read +
  update)
- docs/plans/examples/phase1-sample.md (read, format reference)
- docs/plans/feature-strategies-report-metrics/PLAN.md (create)
- src/csm/ subpackages as required by ROADMAP Phase 1
- tests/unit/ mirroring new src/csm/ modules
- CLAUDE.md (update if new conventions added)
- .claude/knowledge/* and .claude/playbooks/* (create/update as needed)

**Expected deliverables:**
- docs/plans/feature-strategies-report-metrics/PLAN.md — complete plan
  with embedded prompt
- Phase 1 metric computation modules and Pydantic payload models in
  src/csm/
- Unit tests in tests/unit/ with ≥ 90% coverage on new code
- Updated ROADMAP.md and PLAN.md with progress notes and check marks
- Any new/updated .claude/* files + CLAUDE.md
- Single standards-compliant Conventional Commit

Begin by reading the preparation files. Then draft and save the plan.
Do not write implementation code until the plan is complete and saved.
```

---

## Scope

### In scope (Phase 1, csm-set)

- `StrategyReport` Pydantic v2 model + sub-models (gateway-schema-1:1).
- `build_strategy_report` pure function + sub-builders.
- Trade-based metric helpers (`gross_profit`, `gross_loss`,
  `profit_factor`, `expected_payoff`, `avg_winning_trade`,
  `avg_losing_trade`, `largest_winning_trade`,
  `largest_losing_trade`, `pct_profitable`, `ratio_avg_win_avg_loss`,
  `outliers_count`, `outliers_pnl`, `avg_bars_in_trades`,
  `longest_winning_streak`, `longest_losing_streak`).
- `DrawdownAnalyzer.runup_episodes` + derived stats.
- `ClosedTrade` + `pair_trades` FIFO algorithm.
- Offline-first `BenchmarkLoader` reading from `ParquetStore`.
- `LivePortfolioMetrics.report` field + `as_dict()` embeds
  `extended_data.report`.
- `run_post_refresh_hook` builds the report and (soft-skip) writes
  closed-trade rows.
- `GatewayAdapter.write_daily_performance` logs payload size +
  report-presence.
- `CSM_BENCHMARK_SYMBOL` + `CSM_REPORT_ENABLE_PUBLIC` env settings.
- `GET /api/v1/history/strategy-report` endpoint.

### Out of scope (deferred)

- `quant-infra-db` schema changes (Phase 2, separate repo).
- `quant-api-gateway` Pydantic schema / endpoints / cache (Phase 3).
- `quant-dashboard` Zod schemas / tabs / charts / print (Phase 4).
- Intrabar run-up / drawdown values — populated as `None` for csm-set.
- TFEX-specific `margin_usage` — `None` placeholders only.

---

## Design decisions

### D1. `ClosedTrade` is a new Pydantic v2 model

Defined in `src/csm/execution/trade_pairing.py`. Frozen, `Decimal`
fields for monetary values, tz-aware UTC timestamps. Coerces non-UTC
timezones to UTC at the validator boundary.

### D2. `pair_trades()` algorithm — FIFO, per symbol

Each `BUY` opens or adds to a long lot; each `SELL` closes lots
FIFO. Re-entries after flat start a fresh lot. Symmetrical short
support for future TFEX. Pure function, no I/O. Commission is split
proportionally across partial-exit slices. Mixed long+short within a
single symbol's fill stream is rejected with `TradePairingError`.

### D3. `StrategyReport` is gateway-schema-1:1

All sub-models (`Headline`, `ProfitStructure`, `Returns`,
`BenchmarkComparison`, `RiskAdjusted`, `TradesAnalysis`, `Details`,
`CapitalEfficiency`, `RunUpsDrawdowns`, `TradeLogEntry`,
`BenchmarkPoint`, …) live in `strategy_report_models.py`. All
monetary / ratio / percentage fields are `Decimal`. Frozen,
`extra="forbid"`. Intrabar / margin fields default to `None`.

### D4. Serialization shape

`model_dump(mode="json")` emits every `Decimal` as a string. The
gateway adapter stores the resulting dict verbatim into the JSONB
`metadata` column. The dashboard later coerces via
`z.coerce.number()`.

### D5. P&L distribution buckets

1%-wide buckets in [-10%, +10%], with overflow buckets `< -10%` and
`> +10%`. Each bucket emits `{bucket_low_pct, bucket_high_pct,
count, kind}` where `kind ∈ {"loss", "profit", "breakeven"}`.

### D6. Benchmark loader is offline-first

Reads benchmark close-price column from existing `ParquetStore`
(`prices_latest` by default). Normalises first observation to
`initial_capital`. Missing column → `BenchmarkUnavailableError`,
which the hook catches and logs at WARNING (the report is emitted
without benchmark fields).

### D7. `runup_episodes` mirrors `recovery_periods`

Same loop, inverted sign. Returns
`pd.DataFrame[start, peak, end, height, duration_days, height_months]`.

### D8. Settings additions

`benchmark_symbol: str = "^SET.BK"` and `report_enable_public: bool =
True`. `Settings` model remains `frozen=True`.

### D9. History endpoint mines the JSONB metadata

`GET /api/v1/history/strategy-report` reads the most recent 30
`daily_performance` rows via `GatewayAdapter.read_daily_performance`
and returns the first row whose `metadata["extended_data"]["report"]`
is a dict. 503 when gateway adapter is unavailable, 404 when no
report exists. The path is under the existing `/history` prefix and
therefore subject to the existing public-mode block.

### D10. `trade_history` soft-skip

The existing `trade_history` schema in `db_csm_set` does not yet
carry `entry_price` / `exit_price` / `realized_pnl` /
`duration_bars` (Phase 2). The hook persists the closed-trade rows
in a best-effort try/except — Postgres errors (e.g. CHECK constraint
on `side`) are logged at WARNING and never propagate. Phase 1
therefore degrades gracefully: the report always ships in
`daily_performance.metadata`; trade rows ship once Phase 2 lands.

---

## Implementation steps

1. **Branch hygiene** — `feature/strategy-report-metrics-phase1` off
   `live-test`.
2. **Settings** — add `benchmark_symbol`, `report_enable_public`.
3. **Execution** — `errors.py`, `trade_pairing.py`, exports.
4. **Risk metrics** — `trade_metrics.py` and `__init__.py` re-exports.
5. **Drawdown** — `runup_episodes` + derived stats on
   `DrawdownAnalyzer`.
6. **Data** — `BenchmarkLoader` + `BenchmarkUnavailableError`.
7. **Research** — `strategy_report_models.py`, `strategy_report.py`,
   `ReportError`.
8. **Live** — `LivePortfolioMetrics.report` + `as_dict()` change.
9. **Adapters** — hook build + soft-skip trade write + gateway log
   line.
10. **API** — `StrategyReportResponse` schema + `/history/strategy-
    report` route.
11. **Tests** — every module mirrored under `tests/unit/`, plus
    integration tests for the new route.
12. **Quality gate** — `ruff`, `ruff format`, `mypy`, `pytest`.
13. **Docs** — this plan + umbrella ROADMAP ticks.
14. **Commit** — single Conventional Commit.

---

## File changes

### Source

| File | Action | Notes |
|---|---|---|
| `src/csm/config/settings.py` | MODIFY | +`benchmark_symbol`, `report_enable_public`. |
| `src/csm/research/strategy_report.py` | CREATE | Pure builder. |
| `src/csm/research/strategy_report_models.py` | CREATE | Pydantic v2 sub-models. |
| `src/csm/research/exceptions.py` | MODIFY | +`ReportError`. |
| `src/csm/research/__init__.py` | MODIFY | New re-exports. |
| `src/csm/risk/trade_metrics.py` | CREATE | Stand-alone trade metrics. |
| `src/csm/risk/drawdown.py` | MODIFY | +`runup_episodes` + derived stats. |
| `src/csm/risk/__init__.py` | MODIFY | New re-exports. |
| `src/csm/execution/trade_pairing.py` | CREATE | FIFO pairing + `ClosedTrade`. |
| `src/csm/execution/errors.py` | CREATE | `ExecutionError`, `TradePairingError`. |
| `src/csm/execution/__init__.py` | MODIFY | New re-exports. |
| `src/csm/data/benchmark.py` | CREATE | Offline-first benchmark loader. |
| `src/csm/data/exceptions.py` | MODIFY | +`BenchmarkUnavailableError`. |
| `src/csm/data/__init__.py` | MODIFY | New re-exports. |
| `src/csm/live/portfolio.py` | MODIFY | +`report` field, extended `as_dict()`. |
| `src/csm/adapters/hooks.py` | MODIFY | Build report, replace metrics, persist trades. |
| `src/csm/adapters/gateway.py` | MODIFY | Payload-size / report-presence log line. |
| `api/routers/history.py` | MODIFY | `GET /strategy-report` route. |
| `api/schemas/history.py` | MODIFY | `StrategyReportResponse`. |

### Tests

| File | Action |
|---|---|
| `tests/unit/config/test_settings.py` | MODIFY |
| `tests/unit/execution/test_trade_pairing.py` | CREATE |
| `tests/unit/risk/test_metrics_extended.py` | CREATE |
| `tests/unit/risk/test_drawdown_runups.py` | CREATE |
| `tests/unit/data/test_benchmark_loader.py` | CREATE |
| `tests/unit/research/test_strategy_report.py` | CREATE |
| `tests/unit/live/test_portfolio.py` | MODIFY |
| `tests/unit/adapters/test_hooks_report_payload.py` | CREATE |
| `tests/integration/test_api_history.py` | MODIFY (TestStrategyReport class) |

### Docs

| File | Action |
|---|---|
| `docs/plans/feature-strategies-report-metrics/PLAN.md` | CREATE (this file) |
| `../../plans/feature-strategies-report-metrics/ROADMAP.md` | MODIFY (tick Phase 1, status) |

---

## Success criteria

- [x] `StrategyReport` round-trips through `model_dump_json` →
  `model_validate_json` losslessly.
- [x] `pair_trades` handles single round-trip, partial fills, multi-lot
  FIFO consumption, re-entries, interleaved symbols, short-side
  pairing, and rejects negative quantities / naive timestamps.
- [x] `runup_episodes` mirrors `recovery_periods` shape; empty input
  → empty DataFrame.
- [x] `BenchmarkLoader.load` normalises first observation to
  `initial_capital`; raises `BenchmarkUnavailableError` on missing
  column / tz-naive index / empty filter range.
- [x] `run_post_refresh_hook` produces a `gateway.write_daily_performance`
  payload that contains `extended_data.report` when prices and the
  live config are present.
- [x] `GET /api/v1/history/strategy-report` returns the latest
  `extended_data.report` from `daily_performance.metadata`;
  503/404 codes behave per pattern.
- [x] Test suite green; `--cov-fail-under=90` for `src/csm/adapters/`
  and `api/` (verified at the quality-gate step).

---

## Progress notes

- 2026-05-21 — Plan drafted, branch created off `live-test`.
- 2026-05-21 — Settings, trade pairing, trade metrics, run-up,
  benchmark loader landed with green local test runs.
- 2026-05-21 — `StrategyReport` builder + sub-models (split into
  `strategy_report.py` and `strategy_report_models.py` to stay under
  the 400-line budget) green: 12/12 tests passing.
- 2026-05-21 — Hooks wire the report into the gateway payload;
  existing 25 hook tests + 3 new payload tests all green. Soft-skip
  fallback for `trade_history` writes is in place — confirmed by
  fixture asserting no exception escapes when the table rejects new
  shape.
- 2026-05-21 — `GET /api/v1/history/strategy-report` endpoint plus
  5 integration tests (public-mode 403, 503-on-no-adapter, happy
  path, 404 missing report, 404 empty rows) all green.

---

## Completion notes

### Summary

Phase 1 lands the full csm-set surface required by the umbrella
report-metrics feature without changing any external contracts.
Existing live-test data flow remains unchanged when the live config
is absent; when present, the gateway `daily_performance.metadata`
column now carries the strategy report under
`extended_data.report`.

### Deviations / follow-ups

1. **Trade-row persistence is a soft-skip until Phase 2.** The
   current `db_csm_set.trade_history` schema does not accept the new
   columns; the hook catches the schema error and logs WARNING. Once
   Phase 2 lands the migration (umbrella ROADMAP), the same hook will
   begin persisting rows successfully without code changes — only the
   adapter SQL needs to evolve.
2. **Refresh-path trade log is empty for now.** Reconstructing the
   historical fill stream from the existing rebalance trade tables
   was deemed out of scope for Phase 1. The report still ships with
   `trades=[]`; the trade log will populate from Phase 2 onward as
   richer rows are written.
3. **Sub-models split** — Pre-emptively split into
   `strategy_report_models.py` to keep both files inside the 400-line
   budget.
