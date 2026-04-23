# CSM-SET Roadmap

Cross-sectional momentum strategy system for the SET market.
Development phases ordered by dependency — each phase must be complete and validated before the next begins.

---

## Status Legend

| Symbol | Meaning |
|--------|---------|
| `[ ]` | Not started |
| `[~]` | In progress |
| `[x]` | Complete |
| `[-]` | Skipped / deferred |

---

## Phase 0 — Project Bootstrap

> Goal: working repo, clean tooling, everyone can `uv sync` and run quality gates.

- [ ] Initialise git repo and push to GitHub
- [ ] `uv init` and configure `pyproject.toml` (all dependency groups)
- [ ] Install pre-commit hooks (`ruff`, `mypy`)
- [ ] Verify quality gates pass on empty project
  - [ ] `uv run ruff check .`
  - [ ] `uv run ruff format --check .`
  - [ ] `uv run mypy src/`
  - [ ] `uv run pytest tests/ -v`
- [ ] Create `.env` from `.env.example`
- [ ] Commit: `chore: initial project scaffold`

**Exit criteria:** `uv sync --all-groups` completes, all quality gates green, CI passes.

---

## Phase 1 — Data Pipeline

> Goal: reliable OHLCV data for all SET symbols stored in parquet, reproducible and versioned.

### 1.1 Config & Constants

- [x] `src/csm/config/constants.py` — SET sector codes, index symbol, thresholds
- [x] `src/csm/config/settings.py` — `Settings` via pydantic-settings, env var binding
  - [x] Include `public_mode: bool = False` field
  - [x] Include `results_dir: Path = Path("./results")` field
- [x] Unit test: settings load from `.env` correctly

### 1.2 Storage Layer

- [x] `src/csm/data/store.py` — `ParquetStore`: save / load / exists / list_keys
- [x] Unit test: round-trip save → load preserves DataFrame dtypes and index
- [x] Create `data/raw/`, `data/processed/`, `data/universe/` (gitignored)
- [x] Create `results/notebooks/`, `results/backtest/`, `results/signals/` (committed to git)

### 1.3 tvkit Loader

- [x] `src/csm/data/loader.py` — async `OHLCVLoader` wrapping tvkit `OHLCV`
  - [x] `fetch(symbol, interval, bars)` — single symbol
  - [x] `fetch_batch(symbols, interval, bars)` — concurrent, rate-limit safe
  - [x] Retry on transient errors, log failures without crashing batch
  - [x] Raise `DataAccessError` immediately when `settings.public_mode=True`
- [x] Unit test: mock tvkit, assert DataFrame schema (OHLCV + DatetimeIndex)
- [x] Unit test: `DataAccessError` raised when public_mode=True
- [-] Integration smoke test: fetch `SET:SET` 1D 100 bars (manual only, skipped in CI)

### 1.4 Universe Builder

- [x] Collect SET symbol list → save to `data/universe/symbols.json`
  - Source: `settfex` Python library (PyPI: `settfex>=0.1.0`) via `get_stock_list()` + `filter_by_market("SET")`
- [x] `src/csm/data/universe.py` — `UniverseBuilder`
  - [x] Filter: price ≥ 1 THB
  - [x] Filter: 90-day trailing avg volume ≥ threshold
  - [x] Filter: data coverage ≥ 80% in lookback window (no look-ahead)
  - [x] Output: dated universe snapshots (one parquet per rebalance date)
- [x] `scripts/build_universe.py` — fetches symbols, saves JSON, builds all snapshots
- [x] Unit tests: 6 tests covering all filters, missing-symbol guard, no-look-ahead, snapshot count

### 1.5 Price Cleaner

- [x] `src/csm/data/cleaner.py` — `PriceCleaner`
  - [x] Forward-fill gaps ≤ 5 trading days
  - [x] Drop symbols with > 20% missing in any rolling year
  - [x] Winsorise daily returns at 1st / 99th percentile
- [x] Unit test: gap fill, winsorise, drop logic

### 1.6 Bulk Fetch Script

- [x] `scripts/fetch_history.py` — fetch 1D 20-year history for all universe symbols
  - [x] Skip already-fetched symbols (idempotent)
  - [x] Log progress (symbol count, failures)
  - [x] Authenticate via tvkit browser session for full bar history
- [x] Run script, verify `data/raw/` populated

### 1.7 Data Quality Check

- [x] Notebook `01_data_exploration.ipynb`
  - [x] Missing data heatmap
  - [x] Return distribution by year
  - [x] Liquidity distribution (avg daily turnover)
  - [x] Survivorship bias audit: confirm delisted symbols present

**Exit criteria:** clean parquet for ≥ 400 SET symbols, 15+ years daily history, data quality notebook shows no critical gaps.

---

## Phase 2 — Signal Research

> Goal: quantify which momentum signals carry alpha on SET. IC > 0.03 and ICIR > 0.3 required to proceed.

### 2.1 Momentum Features

- [ ] `src/csm/features/momentum.py` — `MomentumFeatures`
  - [ ] `mom_12_1`: 12-month return, skip last month (Jegadeesh–Titman)
  - [ ] `mom_6_1`: 6-month return, skip last month
  - [ ] `mom_3_1`: 3-month return, skip last month
  - [ ] `mom_1_0`: 1-month return (expect reversal — use as negative signal)
- [ ] Unit test: correct return calculation vs manual pandas computation
- [ ] Unit test: no look-ahead bias (signal uses only data up to `t-skip`)

### 2.2 Risk-Adjusted Features

- [ ] `src/csm/features/risk_adjusted.py` — `RiskAdjustedFeatures`
  - [ ] `sharpe_momentum`: return / volatility over formation period
  - [ ] `residual_momentum`: alpha vs SET index (remove market beta)
- [ ] Unit test: sharpe_momentum output bounded, residual is market-neutral

### 2.3 Sector Features

- [ ] `src/csm/features/sector.py` — `SectorFeatures`
  - [ ] Relative strength of each symbol vs its sector index
- [ ] Unit test: relative strength = 0 for index itself

### 2.4 Feature Pipeline

- [ ] `src/csm/features/pipeline.py` — `FeaturePipeline`
  - [ ] Combine all features into panel DataFrame: (date, symbol) → features
  - [ ] Winsorise at 1st / 99th cross-sectionally per rebalance date
  - [ ] Z-score normalise cross-sectionally (mean 0, std 1)
- [ ] Unit test: no data leakage across rebalance dates
- [ ] Unit test: z-score mean ≈ 0 and std ≈ 1 per date

### 2.5 Ranking

- [ ] `src/csm/research/ranking.py` — `CrossSectionalRanker`
  - [ ] Percentile rank per rebalance date
  - [ ] Assign quintile labels (Q1 loser → Q5 winner)
- [ ] Unit test: ranks sum to N*(N+1)/2, quintile counts balanced

### 2.6 IC Analysis

- [ ] `src/csm/research/ic_analysis.py` — `ICAnalyzer`
  - [ ] Pearson IC: corr(signal_t, forward_return_t+1M)
  - [ ] Spearman rank IC
  - [ ] ICIR = mean(IC) / std(IC)
  - [ ] Decay curve: IC at horizons 1M, 2M, 3M, 6M, 12M
- [ ] Unit test: IC against known synthetic data

### 2.7 Signal Research Notebook

- [ ] Notebook `02_signal_research.ipynb`
  - [ ] IC time series for each signal
  - [ ] ICIR table: all signals ranked
  - [ ] Signal correlation matrix (check redundancy)
  - [ ] Decay curves
  - [ ] Quintile return spreads (Q5 − Q1) by year
  - [ ] **Decision**: which signals to include in the composite score

**Exit criteria:** at least one signal with ICIR > 0.3 on SET. Composite signal defined and documented.

---

## Phase 3 — Backtesting

> Goal: walk-forward backtest of the composite signal with realistic cost assumptions.

### 3.1 Backtest Engine

- [ ] `src/csm/research/backtest.py` — `MomentumBacktest`
  - [ ] Monthly rebalance on last trading day of month
  - [ ] Survivorship-bias-safe universe (use dated universe snapshots)
  - [ ] Transaction cost: 15 bps per side (0.15%) round-trip
  - [ ] Position sizing: equal weight by default
  - [ ] Output: `BacktestResult` with equity curve, positions history, turnover log
- [ ] Pydantic models: `BacktestConfig`, `BacktestResult`
  - [ ] `BacktestResult.metrics_dict()` → JSON-serialisable dict (no raw prices)
  - [ ] `BacktestResult.equity_curve_dict()` → NAV indexed to 100 (no absolute prices)
  - [ ] `BacktestResult.annual_returns_dict()` → year → return float
- [ ] Unit test: zero-cost backtest of perfect signal returns correct PnL
- [ ] Unit test: transaction cost reduces return by expected amount

### 3.2 Performance Metrics

- [ ] `src/csm/risk/metrics.py` — `PerformanceMetrics`
  - [ ] CAGR, Sharpe, Sortino, Calmar, Max Drawdown
  - [ ] Win rate, avg monthly return, annualised volatility
  - [ ] Alpha and Beta vs SET index
- [ ] Unit test: Sharpe ratio vs manual calculation

### 3.3 Drawdown Analysis

- [ ] `src/csm/risk/drawdown.py` — `DrawdownAnalyzer`
  - [ ] Max drawdown, underwater curve, recovery statistics

### 3.4 Backtest Notebook

- [ ] Notebook `03_backtest_analysis.ipynb`
  - [ ] Equity curve vs SET TRI benchmark
  - [ ] Annual return bar chart
  - [ ] Rolling Sharpe (12-month window)
  - [ ] Drawdown chart
  - [ ] Performance table by formation period
  - [ ] Sensitivity analysis: top_quantile 10% / 20% / 30%
  - [ ] **Decision**: final parameter set

**Exit criteria:** walk-forward CAGR > SET benchmark, Sharpe > 0.5, max drawdown documented.

---

## Phase 4 — Portfolio Construction & Risk

> Goal: production-ready portfolio construction with regime awareness.

### 4.1 Portfolio Construction

- [ ] `src/csm/portfolio/construction.py` — `PortfolioConstructor`
  - [ ] Top-quintile selection from ranked signal
  - [ ] Sector diversification constraint (max 40% in any one sector)
  - [ ] Min position size (1% floor), max position size (10% cap)
- [ ] Unit test: weight constraints satisfied

### 4.2 Weight Optimizer

- [ ] `src/csm/portfolio/optimizer.py` — `WeightOptimizer`
  - [ ] Equal weight, vol-target, minimum-variance
- [ ] Unit test: all schemes sum to 1.0, no negative weights

### 4.3 Rebalance Scheduler

- [ ] `src/csm/portfolio/rebalance.py` — `RebalanceScheduler`
  - [ ] Last trading day of month schedule
  - [ ] Turnover calculation and trade list output

### 4.4 Regime Detection

- [ ] `src/csm/risk/regime.py` — `RegimeDetector`
  - [ ] BULL / BEAR / NEUTRAL via 200-day SMA + 3M return
  - [ ] BEAR → reduce allocation to 50%
- [ ] Unit test: regime transitions on known price series

### 4.5 Portfolio Optimization Notebook

- [ ] Notebook `04_portfolio_optimization.ipynb`
  - [ ] Equal vs vol-target vs min-variance equity curves
  - [ ] Regime-filtered vs unfiltered performance
  - [ ] Sector exposure over time, turnover analysis
  - [ ] **Decision**: final portfolio construction config

**Exit criteria:** regime filter reduces drawdown in bear periods.

---

## Phase 5 — API

> Goal: FastAPI serving live signals and portfolio via REST, with daily auto-refresh and public mode enforcement.

### 5.1 App Factory

- [ ] `api/main.py` — app factory with lifespan, CORS, router mounting
  - [ ] Public mode middleware: block write endpoints when `CSM_PUBLIC_MODE=true`
  - [ ] Mount `results/notebooks/` as `/static/notebooks/` (StaticFiles)
- [ ] `/health` returns `{"status": "ok", "version": "...", "public_mode": true/false}`

### 5.2 Routers

- [ ] `api/routers/universe.py` — `GET /api/v1/universe`
- [ ] `api/routers/signals.py` — `GET /api/v1/signals/latest`
  - [ ] Public mode: read from `results/signals/latest_ranking.json`
  - [ ] Private mode: compute from live feature matrix
- [ ] `api/routers/portfolio.py` — `GET /api/v1/portfolio/current`
  - [ ] Public mode: read from `results/backtest/summary.json`
- [ ] `api/routers/backtest.py` — `POST /api/v1/backtest/run` → 403 in public mode
- [ ] `api/routers/data.py` — `POST /api/v1/data/refresh` → 403 in public mode
- [ ] Integration tests: all public-mode read endpoints return data without credentials

### 5.3 Daily Scheduler

- [ ] `api/scheduler/jobs.py` — APScheduler, weekday 18:00 Asia/Bangkok
  - [ ] Skip all jobs when `public_mode=True`
- [ ] `scripts/refresh_daily.py` — manual trigger (private only)
- [ ] `scripts/export_results.py` — **NEW**: regenerate `results/` for git commit

**Exit criteria:** API starts in public mode with no credentials, read endpoints return results/ data correctly.

---

## Phase 6 — Web Dashboard (UI)

> Goal: NiceGUI dashboard functional in both private and public mode from single Docker image.

### 6.1 App Shell

- [ ] `ui/main.py` — NiceGUI mounted on FastAPI app via `ui.run(fastapi_app=app)`
- [ ] Nav sidebar: Dashboard / Signals / Backtest / Notebooks / Universe
- [ ] Public mode banner: "Read-only mode — pre-computed results only"

### 6.2 Dashboard Page

- [ ] `ui/pages/dashboard.py`
  - [ ] Regime badge, portfolio snapshot, SET index sparkline
  - [ ] "Refresh Data" button visible **only** when `public_mode=False`

### 6.3 Signals Page

- [ ] `ui/pages/signals.py`
  - [ ] Signal heatmap + ranked table (reads from `results/` in public mode)

### 6.4 Backtest Page

- [ ] `ui/pages/backtest.py`
  - [ ] Public mode: pre-computed equity curve + metrics from `results/backtest/`
  - [ ] Private mode: config form + run button + live output

### 6.5 Notebooks Page (new)

- [ ] `ui/pages/notebooks.py` — tabbed iframe viewer for static HTML notebooks
  - [ ] Tabs: Data Exploration / Signal Research / Backtest Analysis / Portfolio Optimization
  - [ ] Each tab renders `results/notebooks/<name>.html` via iframe
  - [ ] Graceful fallback message if HTML file not yet exported

### 6.6 Universe Page

- [ ] `ui/pages/universe.py` — filterable symbol table

### 6.7 Chart & Table Components

- [ ] `ui/components/charts.py` — equity curve, IC chart, drawdown chart
- [ ] `ui/components/tables.py` — signal table, portfolio table

**Exit criteria:** all pages load and display pre-computed data without credentials.

---

## Phase 7 — Docker & Public Distribution

> Goal: `git clone` + `docker compose up` → research visible at `localhost:8080`. Zero setup required.

### 7.1 Dockerfile

- [ ] `Dockerfile` — single image: python:3.11-slim + uv + source + `results/`
- [ ] Default `ENV CSM_PUBLIC_MODE=true`
- [ ] Expose ports 8000 (API) and 8080 (UI)

### 7.2 Docker Compose

- [ ] `docker-compose.yml` — public mode, `results/` mounted read-only
  ```yaml
  volumes:
    - ./results:/app/results:ro
  ```
- [ ] `docker-compose.private.yml` — owner override
  ```yaml
  # docker compose -f docker-compose.yml -f docker-compose.private.yml up
  environment:
    CSM_PUBLIC_MODE: "false"
    TVKIT_BROWSER: "chrome"
  volumes:
    - ./data:/app/data          # live data directory
    - ./results:/app/results    # writable for export_results.py
  ```
- [ ] Test: `docker compose up` from fresh clone with no `.env` → no errors

### 7.3 Export Results Script

- [ ] `scripts/export_results.py` — complete and tested
  - [ ] Export 4 notebooks to `results/notebooks/*.html`
    - `jupyter nbconvert --to html --execute --no-input`
  - [ ] Export `results/backtest/summary.json` — metrics only, no prices
  - [ ] Export `results/backtest/equity_curve.json` — NAV indexed to 100
  - [ ] Export `results/backtest/annual_returns.json`
  - [ ] Export `results/signals/latest_ranking.json` — scores/quintiles only
- [ ] Owner workflow:
  ```bash
  uv run python scripts/export_results.py
  git add results/
  git commit -m "results: update YYYY-MM-DD"
  git push
  ```

### 7.4 Data Boundary Audit

- [ ] `results/backtest/equity_curve.json` — NAV only, no absolute prices
- [ ] `results/signals/latest_ranking.json` — scores/quintiles only, no OHLCV
- [ ] Notebook HTML (`--no-input`) — charts visible, no raw data tables
- [ ] `.gitignore` excludes all of `data/` directory

### 7.5 README Update

- [ ] Quick Start section:
  ```bash
  git clone https://github.com/lumduan/csm-set
  cd csm-set
  docker compose up
  # open http://localhost:8080
  ```
- [ ] "What you will see" section: notebooks, backtest results, signal rankings
- [ ] "What requires credentials" section: data fetch, notebook re-execution
- [ ] Owner workflow section: fetch → export_results → git add results/ → push

**Exit criteria:** fresh `git clone` + `docker compose up` → all notebook pages load, backtest chart renders, signal rankings visible. Zero errors in container logs.

---

## Phase 8 — Hardening & Documentation

> Goal: production-ready quality, complete documentation.

### 8.1 Test Coverage

- [ ] All unit tests passing
- [ ] All integration tests passing (public mode + private mode variants)
- [ ] Coverage ≥ 80% on `src/csm/`

### 8.2 Documentation

- [ ] All `docs/` pages complete
- [ ] `docs/guides/public-mode.md` — **NEW**: data boundaries, Docker, owner workflow
- [ ] `README.md` — full, with quick start and badges

### 8.3 CI

- [ ] `ci.yml`: lint → type-check → test → docker build check on every push
- [ ] CI step: verify `results/` contains required files (fail if missing)

**Exit criteria:** all tests green, Docker builds in CI, docs complete.

---

## Phase 9 — Enhancement (Post-MVP)

> Optional upgrades after Phase 8 is complete.

- [ ] Fundamental filter (P/BV, ROE) via SET SMART
- [ ] Foreign flow signal from SET website
- [ ] LightGBM ranking model
- [ ] Intraday entry timing using 1H data
- [ ] Multi-factor composite: momentum + value + quality

---

## Dependency Map

```
Phase 0 (Bootstrap)
    └── Phase 1 (Data Pipeline)
            └── Phase 2 (Signal Research)
                    └── Phase 3 (Backtesting)
                            └── Phase 4 (Portfolio & Risk)
                                    ├── Phase 5 (API)
                                    │       └── Phase 6 (UI)
                                    │               └── Phase 7 (Docker & Public)
                                    │                           └── Phase 8 (Hardening)
                                    └── Phase 9 (Enhancement)
```

---

## Estimated Timeline

| Phase | Scope                        | Estimate   |
|-------|------------------------------|------------|
| 0     | Bootstrap                    | 1 day      |
| 1     | Data Pipeline                | 1–2 weeks  |
| 2     | Signal Research              | 1–2 weeks  |
| 3     | Backtesting                  | 1 week     |
| 4     | Portfolio & Risk             | 1 week     |
| 5     | API                          | 3–4 days   |
| 6     | UI                           | 1 week     |
| 7     | Docker & Public Distribution | 3–4 days   |
| 8     | Hardening & Docs             | 1 week     |
| 9     | Enhancement (optional)       | open-ended |

**MVP with public distribution (Phase 0–7): ~9–11 weeks**

---

## Current Status

> Update this section as phases complete.

- **Active phase:** Phase 2 — Signal Research
- **Completed phases:** Phase 1 (Data Pipeline) — all sub-phases 1.1–1.7 complete as of 2026-04-23
  - 1.1 Config & Constants, 1.2 Storage Layer, 1.3 tvkit Loader, 1.4 Universe Builder, 1.5 Price Cleaner, 1.6 Bulk Fetch Script, 1.7 Data Quality Check (all 6 sign-off checks PASS)
- **Blocked by:** nothing
