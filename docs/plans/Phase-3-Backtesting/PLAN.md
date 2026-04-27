# Phase 3 — Backtesting Master Plan

**Feature:** Walk-Forward Momentum Backtest Engine for SET Market
**Branch:** `feature/phase-3-backtesting`
**Created:** 2026-04-27
**Status:** In progress — 3.1–3.3 scaffolded; 3.4 notebook empty; unit tests thin
**Positioning:** Validation layer — consumes Phase 2 composite signal and Phase 1 clean data to produce a walk-forward equity curve that proves or disproves the signal's alpha hypothesis before any live capital is risked

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

Phase 3 builds the **backtesting engine** that validates the cross-sectional momentum strategy developed in Phase 2. It ingests the feature panel produced by `FeaturePipeline`, ranks stocks monthly using `CrossSectionalRanker`, constructs a long-only top-quintile portfolio, simulates realistic transaction costs, and computes the full suite of performance and risk metrics. The resulting equity curve, annual returns, drawdown analysis, and benchmark comparison are documented in a research notebook that serves as the Phase 3 exit gate.

Every downstream phase depends on the findings here: Phase 4 (Portfolio & Risk) builds on the backtest's regime-awareness; Phases 5–6 serve the backtest results via API and UI; Phase 7 exports the results to `results/backtest/` for public consumption.

### Scope

Phase 3 covers four sub-phases in dependency order:

| Sub-phase | Deliverable | Purpose |
|---|---|---|
| 3.1 | Backtest Engine | `MomentumBacktest` — monthly rebalance, cost model, equity curve |
| 3.2 | Performance Metrics | `PerformanceMetrics` — CAGR, Sharpe, Sortino, Calmar, alpha/beta |
| 3.3 | Drawdown Analysis | `DrawdownAnalyzer` — underwater curve, episode recovery table |
| 3.4 | Backtest Notebook | `03_backtest_analysis.ipynb` — equity curve, charts, sensitivity, decision |

**Out of scope for Phase 3:**

- Portfolio construction weight optimisation (Phase 4 — `WeightOptimizer`)
- Regime-filtered allocation (Phase 4 — `RegimeDetector`)
- Live data refresh and scheduled backtest runs (Phase 5)
- API endpoints for backtest results (Phase 5)
- Dashboard backtest page (Phase 6)
- `results/backtest/` export for public Docker image (Phase 7)

### Current State (as of 2026-04-27)

Phases 3.1–3.3 are structurally complete — the core modules were scaffolded during earlier phases. What remains is **completing the unit test suite** and **writing the research notebook**.

| Module | Lines | Status |
|---|---|---|
| `src/csm/research/backtest.py` | 175 | `[x]` Implemented + bug-fixed (2026-04-27) — `CrossSectionalRanker` misuse removed; `_select_top_quantile()` added |
| `src/csm/risk/metrics.py` | 103 | `[x]` Implemented + ddof-fix (2026-04-27) — beta now uses `cov(ddof=0)` for consistency |
| `src/csm/risk/drawdown.py` | 57 | `[x]` Implemented — `DrawdownAnalyzer` with underwater curve and episode table |
| `notebooks/03_backtest_analysis.ipynb` | 0 | `[ ]` Empty — needs all cells written |
| `tests/unit/research/test_backtest.py` | 130 | `[x]` Complete (2026-04-27) — 8 unit tests, all pass |
| `tests/unit/risk/test_metrics.py` | 110 | `[x]` Complete (2026-04-27) — 9 unit tests (extended from 1), all pass |
| `tests/unit/risk/test_drawdown.py` | 80 | `[x]` Complete (2026-04-27) — 6 unit tests, all pass |
| `tests/integration/test_backtest_pipeline.py` | 26 | `[x]` 1 integration smoke test — prices→features→backtest round-trip |

---

## Problem Statement

The Phase 2 signal research produced a composite momentum score with measured IC > 0.03 and ICIR > 0.3. But IC is a correlation metric, not a PnL metric. Several non-trivial problems must be solved before we can claim the strategy is tradeable:

1. **Transaction costs erode alpha** — SET brokerage is ~15 bps per side. Monthly rebalancing of a 30–50 stock portfolio generates turnover that must be deducted from gross returns to produce realistic net returns.
2. **Survivorship bias at rebalance time** — Using today's universe to populate historical rebalance dates silently inflates historical returns. Each rebalance must draw from the dated universe snapshot at that date.
3. **No-look-ahead price data** — Forward returns used to measure period performance must only use prices available after the rebalance date. The feature panel's signal must be formed from data available at rebalance time with no knowledge of next-period prices.
4. **Benchmark comparison** — Raw CAGR without a benchmark comparison is uninformative. The strategy must beat the SET Total Return Index on a risk-adjusted basis (Sharpe) to justify the complexity.
5. **Drawdown documentation** — Investors tolerate strategy risk only if its worst-case behaviour is understood. Max drawdown, underwater duration, and recovery periods must be explicitly measured and documented.
6. **Parameter sensitivity** — A backtest that only works for one specific `top_quantile` or `formation_months` is overfit. Sensitivity analysis across parameter combinations is required to confirm robustness.

---

## Design Rationale

### Walk-Forward Simulation

The backtest iterates month-by-month using the same `rebalance_dates` schedule produced by `UniverseBuilder`. At each `current_date`:

1. Rank the universe using the feature panel formed as of `current_date`.
2. Select the top `top_quantile` fraction of ranked stocks.
3. Compute target weights via the selected weight scheme.
4. Deduct the transaction cost proportional to turnover from `current_weights` → `target_weights`.
5. Apply the portfolio return over `[current_date, next_date]` to the NAV.

This produces an out-of-sample equity curve because the ranker uses no future data — ranking at `current_date` uses only features constructed from prices available at `current_date`.

### Cost Model

Transaction cost is modelled as `turnover × (transaction_cost_bps / 10_000)`. Turnover is defined as `0.5 × Σ|w_new - w_old|` (one-way turnover). With `transaction_cost_bps = 15`, a full rebalance (100% turnover) costs 15 bps, which is a conservative floor for SET retail execution. This is deducted from gross monthly return before updating NAV.

### Public-Safe Result Contract

`BacktestResult` contains no raw OHLCV prices. The three export methods — `metrics_dict()`, `equity_curve_dict()`, and `annual_returns_dict()` — produce JSON-serialisable outputs containing only derived metrics and NAV (indexed to 100). This is the artefact persisted to `results/backtest/` for the public Docker image.

### Risk-Free Rate

Sharpe and Sortino ratios use `RISK_FREE_RATE_ANNUAL = 0.02` (2% annualised), sourced from `constants.py`. This approximates the Thai overnight rate (THOR) over the backtest period. The constant is centralised so that changing the assumption does not require hunting through multiple modules.

### Benchmark

The SET Total Return Index (`INDEX_SYMBOL = "SET:SET"`) is the benchmark for alpha/beta computation. Beta is computed as `cov(portfolio, benchmark) / var(benchmark)` on aligned monthly returns. Alpha is the annualised intercept. Information ratio is `(mean(portfolio − benchmark) × 12) / (tracking_error × √12)`.

### DataFrame vs. Pydantic at Module Boundaries

The backtest engine receives a `pd.DataFrame` feature panel and a `pd.DataFrame` price matrix as inputs — columnar tabular data for which vectorised pandas operations are mandatory. All non-tabular outputs (config, metrics, results) are Pydantic models. This is consistent with the Phase 1 architectural decision: Pydantic everywhere except OHLCV tabular payloads.

---

## Architecture

### Directory Layout

```
src/csm/
├── research/
│   ├── backtest.py           # BacktestConfig, BacktestResult, MomentumBacktest
│   └── exceptions.py         # BacktestError, ResearchError
├── risk/
│   ├── metrics.py            # PerformanceMetrics.summary()
│   └── drawdown.py           # DrawdownAnalyzer — underwater curve + episode table

notebooks/
└── 03_backtest_analysis.ipynb  # Phase 3 research and sign-off notebook

tests/
├── unit/
│   ├── research/
│   │   └── test_backtest.py      # MomentumBacktest unit tests
│   └── risk/
│       ├── test_metrics.py       # PerformanceMetrics unit tests (extend)
│       └── test_drawdown.py      # DrawdownAnalyzer unit tests
└── integration/
    └── test_backtest_pipeline.py  # Prices → features → backtest integration smoke test
```

### Dependency Graph

```
FeaturePipeline output (Phase 2)
    ↓  feature_panel: pd.DataFrame (date, symbol) → features
MomentumBacktest.run()
    ↓  uses CrossSectionalRanker (Phase 2.5)
    ↓  uses PortfolioConstructor (Phase 4 stub — top-K select only)
    ↓  uses WeightOptimizer (Phase 4 stub — equal weight default)
    ↓  uses RebalanceScheduler (Phase 4 stub — turnover calculation)
    ↓  calls PerformanceMetrics.summary()
BacktestResult (Pydantic)
    ↓  equity_curve_dict() / metrics_dict() / annual_returns_dict()
ParquetStore.save("backtest_equity_curve", ...)
```

### Data Flow

```
data/processed/{SYMBOL}.parquet     ← Phase 1 clean OHLCV
    ↓  FeaturePipeline (Phase 2)
feature panel (date, symbol) → composite z-score
    ↓  MomentumBacktest.run()
equity_curve: {YYYY-MM-DD: NAV}
    ↓  PerformanceMetrics.summary()
metrics: {cagr, sharpe, sortino, calmar, max_drawdown, alpha, beta, ...}
    ↓  DrawdownAnalyzer
underwater curve, episode table
    ↓  BacktestResult → metrics_dict() / equity_curve_dict()
results/backtest/summary.json           ← Phase 7 public export
results/backtest/equity_curve.json      ← Phase 7 public export
results/backtest/annual_returns.json    ← Phase 7 public export
```

---

## Implementation Phases

### Phase 3.1 — Backtest Engine

**Status:** `[x]` Implemented — `src/csm/research/backtest.py` complete (171 → 175 lines after bug fix)
**Unit tests:** `[x]` Complete — `tests/unit/research/test_backtest.py` — all 8 tests pass (2026-04-27)
**Bug fix (2026-04-27):** Critical bug in `run()` loop fixed — `CrossSectionalRanker.rank(feature_panel, current_date)` passed a `pd.Timestamp` as `signal_col` (expects a column name string), causing `ValueError` on every run. `PortfolioConstructor.select()` also had an incompatible API (expected flat `"quintile"` and `"symbol"` columns not present in MultiIndex panel). Both removed from the loop; replaced by `_select_top_quantile()` using `feature_panel.xs(current_date, level="date")` and direct `nlargest` selection. See `docs/plans/phase-3-backtesting/phase3.1_backtest_engine.md`.
**Metrics fix (2026-04-27):** `PerformanceMetrics.summary()` beta calculation used `aligned.cov()` (ddof=1) for covariance but `var(ddof=0)` for benchmark variance, causing β ≠ 1.0 when portfolio = benchmark. Fixed to `aligned.cov(ddof=0)` for consistency.

**Goal:** Vectorised monthly walk-forward momentum backtest. Consumes ranked feature panel and clean price matrix; emits a `BacktestResult` with equity curve, annual returns, per-period positions, turnover log, and performance metrics.

**Implemented classes:**

- `BacktestConfig(BaseModel)`
  - `formation_months: int = 12`
  - `skip_months: int = 1`
  - `top_quantile: float = 0.2`
  - `weight_scheme: str = "equal"` — `"equal"` | `"vol_target"` | `"min_variance"`
  - `start_date: str | None = None`
  - `end_date: str | None = None`
  - `transaction_cost_bps: float = 15.0`

- `BacktestResult(BaseModel)`
  - `config: BacktestConfig`
  - `generated_at: str` — ISO 8601 timestamp
  - `equity_curve: dict[str, float]` — `{YYYY-MM-DD: NAV}`
  - `annual_returns: dict[str, float]` — `{YYYY: return_float}`
  - `positions: dict[str, list[str]]` — `{YYYY-MM-DD: [symbol, ...]}`
  - `turnover: dict[str, float]` — `{YYYY-MM-DD: turnover_fraction}`
  - `metrics: dict[str, float]`
  - `metrics_dict()` → JSON-serialisable dict (metrics only, no prices)
  - `equity_curve_dict()` → NAV indexed to 100 (no absolute prices)
  - `annual_returns_dict()` → `{year: return_float}`

- `MomentumBacktest`
  - `__init__(self, store: ParquetStore)` — composes Ranker, Constructor, Optimizer, Scheduler, Metrics
  - `run(feature_panel, prices, config) -> BacktestResult`
    - Raises `BacktestError` if feature panel or prices empty, or < 2 rebalance dates
    - Iterates `(current_date, next_date)` pairs over rebalance dates
    - Deducts `turnover × (transaction_cost_bps / 10_000)` from gross period return
    - Saves equity curve to `ParquetStore` as `"backtest_equity_curve"` key

**Deliverables (remaining):**

- [x] `tests/unit/research/test_backtest.py` — complete (2026-04-27)
  - [x] Unit test: zero-cost backtest of perfect-rank signal returns correct PnL
  - [x] Unit test: transaction cost of 15 bps reduces return by expected fraction of turnover
  - [x] Unit test: `BacktestError` raised when feature panel is empty
  - [x] Unit test: `BacktestError` raised when only 1 rebalance date provided
  - [x] Unit test: `BacktestError` raised when equity curve is empty after loop
  - [x] Unit test: `BacktestResult.metrics_dict()` contains no raw price data
  - [x] Unit test: `BacktestResult.equity_curve_dict()` NAV starts at 100

---

### Phase 3.2 — Performance Metrics

**Status:** `[x]` Implemented — `src/csm/risk/metrics.py` complete (103 lines after ddof fix)
**Unit tests:** `[x]` Complete — `tests/unit/risk/test_metrics.py` — 9 tests pass (2026-04-27)

**Goal:** Annualised performance metrics from an equity curve. Optionally computes alpha, beta, and information ratio vs. a benchmark.

**Implemented methods:**

- `PerformanceMetrics.summary(equity_curve, benchmark=None) -> dict[str, float]`
  - `cagr` — compound annual growth rate
  - `sharpe` — `(annualised_return - RISK_FREE_RATE_ANNUAL) / annual_volatility`
  - `sortino` — `(annualised_return - RISK_FREE_RATE_ANNUAL) / downside_volatility`
  - `calmar` — `cagr / abs(max_drawdown)`
  - `max_drawdown` — delegated to `DrawdownAnalyzer`
  - `win_rate` — fraction of monthly periods with positive return
  - `avg_monthly_return` — mean of monthly return series
  - `volatility` — annualised standard deviation of monthly returns
  - `alpha`, `beta`, `information_ratio` — only when `benchmark` is provided

**Deliverables (remaining):**

- [x] `tests/unit/risk/test_metrics.py` — complete (2026-04-27)
  - [x] Unit test: CAGR matches manual `(end/start)^(1/years) - 1` for known series
  - [x] Unit test: Sortino is higher than Sharpe when downside vol is small (assertion corrected — plan had wrong direction)
  - [x] Unit test: `max_drawdown` is negative (or zero) for any non-trivial series
  - [x] Unit test: `win_rate` = 0.75 for a 4-period series with 3 positive periods
  - [x] Unit test: `summary()` returns zero-filled dict for empty equity curve
  - [x] Unit test: alpha and beta present in result only when benchmark is provided
  - [x] Unit test: beta ≈ 1.0 when portfolio returns equal benchmark returns exactly

---

### Phase 3.3 — Drawdown Analysis

**Status:** `[x]` Implemented — `src/csm/risk/drawdown.py` complete (57 lines)
**Unit tests:** `[x]` Complete — `tests/unit/risk/test_drawdown.py` — all 6 tests pass (2026-04-27)

**Goal:** Compute the underwater equity curve, peak-to-trough max drawdown, and a table of drawdown episodes with start, trough, recovery dates, depth, and duration.

**Implemented methods:**

- `DrawdownAnalyzer.max_drawdown(equity_curve) -> float` — delegates to `underwater_curve().min()`
- `DrawdownAnalyzer.underwater_curve(equity_curve) -> pd.Series` — `equity / equity.cummax() - 1`
- `DrawdownAnalyzer.recovery_periods(equity_curve) -> pd.DataFrame`
  - Columns: `start`, `trough`, `recovery`, `depth`, `duration_days`
  - One row per completed drawdown episode (open episode at end not included)

**Deliverables (remaining):**

- [x] `tests/unit/risk/test_drawdown.py` — complete (2026-04-27)
  - [x] Unit test: `underwater_curve` is all zeros for a monotonically increasing series
  - [x] Unit test: `max_drawdown` equals `-(peak - trough) / peak` for a known series
  - [x] Unit test: `max_drawdown` is negative (never positive) for any drawdown
  - [x] Unit test: `recovery_periods` returns empty DataFrame for a monotonically increasing series
  - [x] Unit test: `recovery_periods` correctly identifies start, trough, and recovery date for a single known episode
  - [x] Unit test: `duration_days` is consistent with `(recovery - start).days`

---

### Phase 3.4 — Backtest Notebook

**Status:** `[ ]` Empty — `notebooks/03_backtest_analysis.ipynb` exists with 0 cells
**Depends On:** 3.1, 3.2, 3.3 complete; Phase 2 feature panel available

**Goal:** Human sign-off that the backtest is sound and the strategy is worth pursuing to Phase 4. This notebook is the Phase 3 exit gate and the input to the Phase 4 portfolio construction decision.

**Deliverables:**

- [ ] `notebooks/03_backtest_analysis.ipynb` — all cells written in Thai markdown
  - [ ] **เซลล์ตั้งค่า (Setup cell)** — imports, path config, graceful `⚠ DATA NOT AVAILABLE` guard if `data/processed/` empty
  - [ ] **Section 1: ข้อมูลนำเข้า** — load feature panel from `FeaturePipeline`, load clean prices from `ParquetStore`; print universe size and date range
  - [ ] **Section 2: รัน Backtest** — run `MomentumBacktest` with default `BacktestConfig`; print `BacktestResult.metrics_dict()` as a formatted table
  - [ ] **Section 3: เส้น Equity Curve** — equity curve vs SET TRI benchmark (NAV indexed to 100); dual-axis chart with drawdown shading
  - [ ] **Section 4: ผลตอบแทนรายปี** — bar chart of annual strategy returns vs SET annual returns; table of year-by-year comparison
  - [ ] **Section 5: Rolling Sharpe** — 12-month rolling Sharpe ratio time series; mark periods where Sharpe drops below 0
  - [ ] **Section 6: Drawdown Analysis** — underwater curve chart; `DrawdownAnalyzer.recovery_periods()` table sorted by depth; annotate max drawdown date
  - [ ] **Section 7: Sensitivity Analysis** — grid backtest over `top_quantile ∈ {0.1, 0.2, 0.3}` × `formation_months ∈ {3, 6, 12}`; heatmap of Sharpe ratio; confirm robustness
  - [ ] **Section 8: สรุปและการตัดสินใจ** — performance table (CAGR, Sharpe, Sortino, Calmar, MaxDD, alpha, beta, IR); explicit PASS/FAIL against Phase 3 exit criteria; document the chosen final parameter set for Phase 4

**Implementation notes:**

- All markdown cells must be written in Thai per project convention
- Notebook must handle `data/processed/` being empty with a graceful `⚠ DATA NOT AVAILABLE` message per section (not a crash)
- Benchmark series: load `SET:SET` from `ParquetStore(data/processed/)` using the same dividend-adjusted store
- Use `matplotlib` / `seaborn` for charts; no external chart libraries not already in `pyproject.toml`
- Final sign-off cell must use imported constants from `constants.py` (not hardcoded values) for all threshold comparisons

---

## Data Models

### `BacktestConfig`

```python
class BacktestConfig(BaseModel):
    formation_months: int = 12          # lookback window for momentum signal
    skip_months: int = 1                # skip last month (Jegadeesh–Titman)
    top_quantile: float = 0.2           # top 20% of ranked stocks selected
    weight_scheme: str = "equal"        # "equal" | "vol_target" | "min_variance"
    start_date: str | None = None       # ISO date; None = use all available data
    end_date: str | None = None         # ISO date; None = use all available data
    transaction_cost_bps: float = 15.0  # one-way cost in basis points
```

### `BacktestResult`

```python
class BacktestResult(BaseModel):
    config: BacktestConfig
    generated_at: str                       # ISO 8601 timestamp
    equity_curve: dict[str, float]          # {YYYY-MM-DD: NAV} — starts at 100
    annual_returns: dict[str, float]        # {YYYY: net_return_float}
    positions: dict[str, list[str]]         # {YYYY-MM-DD: [symbol, ...]}
    turnover: dict[str, float]              # {YYYY-MM-DD: one_way_turnover}
    metrics: dict[str, float]              # see PerformanceMetrics.summary()
```

### Performance Metrics Contract

| Metric | Description | Type |
|---|---|---|
| `cagr` | Compound annual growth rate | `float` |
| `sharpe` | Annualised Sharpe ratio (rf = 2%) | `float` |
| `sortino` | Annualised Sortino ratio (rf = 2%) | `float` |
| `calmar` | CAGR / abs(max_drawdown) | `float` |
| `max_drawdown` | Peak-to-trough as negative float | `float` |
| `win_rate` | Fraction of periods with positive return | `float` |
| `avg_monthly_return` | Mean monthly return | `float` |
| `volatility` | Annualised monthly return std | `float` |
| `alpha` | Jensen's alpha vs benchmark (annualised) | `float` (optional) |
| `beta` | Portfolio beta vs benchmark | `float` (optional) |
| `information_ratio` | Excess return / tracking error (annualised) | `float` (optional) |

### DrawdownAnalyzer Output

`recovery_periods()` returns a `pd.DataFrame` with schema:

| Column | dtype | Description |
|---|---|---|
| `start` | `pd.Timestamp` | First date equity fell below prior peak |
| `trough` | `pd.Timestamp` | Date of maximum drawdown depth in episode |
| `recovery` | `pd.Timestamp` | First date equity recovered to prior peak |
| `depth` | `float` | Drawdown at trough (negative fraction) |
| `duration_days` | `int` | Calendar days from start to recovery |

---

## Error Handling Strategy

| Scenario | Behaviour |
|---|---|
| `feature_panel` or `prices` empty at backtest start | `BacktestError` raised immediately |
| Fewer than 2 rebalance dates | `BacktestError` raised immediately |
| Equity curve empty after loop (no valid periods) | `BacktestError` raised |
| No stocks pass `top_quantile` filter at a rebalance date | Rebalance skipped; prior weights unchanged; NAV not updated |
| Symbol in `selected` not in `prices` columns | `reindex(...).fillna(0.0)` — missing symbol contributes zero return for that period; logged as warning |
| `PerformanceMetrics.summary()` called with empty equity curve | Returns all-zero dict; does not raise |
| `DrawdownAnalyzer` called on monotonically increasing curve | Returns empty DataFrame from `recovery_periods()`; `max_drawdown` returns 0.0 |

---

## Testing Strategy

### Coverage Target

Minimum 90% line coverage across `src/csm/research/backtest.py` and `src/csm/risk/` for Phase 3 changes. All public methods on all three classes must have dedicated unit tests.

### Mocking Strategy

- `MomentumBacktest` tests: use synthetic `pd.DataFrame` feature panels with known rankings and deterministic price series so expected PnL can be computed by hand
- `PerformanceMetrics` tests: construct equity curves with known mathematical properties (e.g., constant monthly return) to verify metric formulas exactly
- `DrawdownAnalyzer` tests: use hand-constructed price series with deliberate peaks, troughs, and recoveries
- No mocking of `ParquetStore` in unit tests — use `tmp_path` fixture for real file I/O isolation

### Test File Map

| Module | Test file |
|---|---|
| `src/csm/research/backtest.py` | `tests/unit/research/test_backtest.py` |
| `src/csm/risk/metrics.py` | `tests/unit/risk/test_metrics.py` (extend) |
| `src/csm/risk/drawdown.py` | `tests/unit/risk/test_drawdown.py` |
| End-to-end pipeline | `tests/integration/test_backtest_pipeline.py` (extend) |

### Integration Tests

- Marked with `@pytest.mark.integration`; skip in CI via `pytest -m "not integration"`
- `tests/integration/test_backtest_pipeline.py` — extend existing smoke test to assert metric thresholds (not just non-empty result)

---

## Success Criteria

| Criterion | Measure |
|---|---|
| Walk-forward CAGR beats SET TRI | `backtest_result.metrics["cagr"] > benchmark_cagr` over matched date range |
| Sharpe ratio > 0.5 | `backtest_result.metrics["sharpe"] > 0.5` |
| Max drawdown documented | Notebook Section 6 shows underwater curve and episode table |
| Transaction cost model applied | Unit test confirms 15 bps deduction reduces return by expected fraction |
| Survivorship-bias-safe | Each rebalance date draws from the dated universe snapshot, not the current snapshot |
| All unit tests pass | `uv run pytest tests/ -v -m "not integration"` exits 0 |
| Type checking clean | `uv run mypy src/` exits 0 |
| Linting clean | `uv run ruff check src/ scripts/` exits 0 |
| Notebook signs off | All exit-criteria cells in `03_backtest_analysis.ipynb` print `PASS` |
| Parameter sensitivity documented | Section 7 heatmap shows Sharpe > 0 across most parameter combinations |
| No raw prices in `BacktestResult` | `metrics_dict()` and `equity_curve_dict()` contain only derived values |

---

## Future Enhancements

- **Regime filter** — in Phase 4, `RegimeDetector` will reduce allocation to 50% in BEAR periods; `MomentumBacktest` will accept a `regime_series` parameter to apply this overlay
- **Short leg** — long/short backtest for institutional mandates; short leg requires a borrowing cost model
- **Intraday entry timing** — Phase 9 adds 1H OHLCV to simulate better execution timing (vs. close-to-close assumptions used here)
- **Multi-period formation comparison** — automated sweep across all combinations of `formation_months` and `skip_months` stored to `results/backtest/sensitivity/`
- **Bootstrap confidence intervals** — block bootstrap on monthly returns to quantify sampling uncertainty around Sharpe estimate

---

## Commit & PR Templates

### Commit Message (Plan — this commit)

```
plan(backtesting): add master plan for Phase 3 — Backtesting

- Creates docs/plans/Phase-3-Backtesting/PLAN.md
- Documents current implementation state: 3.1–3.3 engines complete,
  unit tests thin, notebook empty
- Covers four sub-phases: Backtest Engine, Performance Metrics,
  Drawdown Analysis, Backtest Notebook
- Specifies walk-forward cost model: 15 bps per-side, dated universe
  snapshots, no look-ahead bias
- Defines BacktestResult public-safe contract: no raw prices in outputs
- Includes full architecture, data models, error handling, test matrix,
  and success criteria

Part of Phase 3 — Backtesting roadmap track.
```

### Commit Message (Implementation — Phase 3.1–3.3 unit tests)

```
test(backtest): add unit tests for MomentumBacktest, PerformanceMetrics, DrawdownAnalyzer

- tests/unit/research/test_backtest.py: zero-cost PnL, cost deduction,
  error paths, public-safe result contract
- tests/unit/risk/test_metrics.py: CAGR, Sortino, max_drawdown, win_rate,
  alpha/beta presence, empty-curve guard
- tests/unit/risk/test_drawdown.py: underwater curve, episode table,
  max_drawdown sign, monotonic series edge case
```

### Commit Message (Implementation — Phase 3.4 Notebook)

```
feat(notebooks): add backtest analysis notebook (Phase 3.4)

- 03_backtest_analysis.ipynb: equity curve vs SET TRI, annual returns,
  rolling Sharpe, drawdown chart, sensitivity heatmap, sign-off table
- All markdown cells in Thai
- Sign-off cell: PASS/FAIL against all Phase 3 exit criteria
```

### PR Description Template

```markdown
## Summary

- Completes Phase 3 — Backtesting unit test coverage and research notebook
- `MomentumBacktest.run()` unit tests: cost model, error paths, public-safe result
- `PerformanceMetrics.summary()` unit tests: all 8 base metrics + alpha/beta
- `DrawdownAnalyzer` unit tests: underwater curve, episode table, edge cases
- `03_backtest_analysis.ipynb`: equity curve, annual returns, rolling Sharpe,
  drawdown analysis, sensitivity heatmap, Phase 3 sign-off

## Test plan

- [ ] `uv run pytest tests/ -v -m "not integration"` — all unit tests pass
- [ ] `uv run mypy src/` — exits 0
- [ ] `uv run ruff check src/ scripts/` — exits 0
- [ ] `uv run ruff format --check src/ scripts/` — no changes
- [ ] Manual: run `03_backtest_analysis.ipynb` with full data — all sign-off cells PASS
- [ ] Manual: confirm equity curve CAGR > SET TRI benchmark CAGR
- [ ] Manual: confirm Sharpe > 0.5
```
