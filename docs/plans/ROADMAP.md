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

- [x] Initialise git repo and push to GitHub
- [x] `uv init` and configure `pyproject.toml` (all dependency groups)
- [x] Install pre-commit hooks (`ruff`, `mypy`)
- [x] Verify quality gates pass on empty project
  - [x] `uv run ruff check .`
  - [x] `uv run ruff format --check .`
  - [x] `uv run mypy src/`
  - [x] `uv run pytest tests/ -v`
- [x] Create `.env` from `.env.example`
- [x] Commit: `chore: initial project scaffold`

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

- [x] `src/csm/features/momentum.py` — `MomentumFeatures`
  - [x] `mom_12_1`: 12-month return, skip last month (Jegadeesh–Titman)
  - [x] `mom_6_1`: 6-month return, skip last month
  - [x] `mom_3_1`: 3-month return, skip last month
  - [x] `mom_1_0`: 1-month return (expect reversal — use as negative signal)
  - [x] Unit test: correct return calculation vs manual pandas computation
  - [x] Unit test: no look-ahead bias (signal uses only data up to `t-skip`)


### 2.2 Risk-Adjusted Features

- [x] `src/csm/features/risk_adjusted.py` — `RiskAdjustedFeatures`
  - [x] `sharpe_momentum`: return / volatility over formation period
  - [x] `residual_momentum`: alpha vs SET index (remove market beta)
  - [x] Unit test: sharpe_momentum output bounded, residual is market-neutral


### 2.3 Sector Features

- [x] `src/csm/features/sector.py` — `SectorFeatures`
  - [x] Relative strength of each symbol vs its sector index
  - [x] Unit test: relative strength = 0 for index itself


### 2.4 Feature Pipeline

- [x] `src/csm/features/pipeline.py` — `FeaturePipeline`
  - [x] Combine all features into panel DataFrame: (date, symbol) → features
  - [x] Winsorise at 1st / 99th cross-sectionally per rebalance date
  - [x] Z-score normalise cross-sectionally (mean 0, std 1)
  - [x] Unit test: no data leakage across rebalance dates
  - [x] Unit test: z-score mean ≈ 0 and std ≈ 1 per date


### 2.5 Ranking

- [x] `src/csm/research/ranking.py` — `CrossSectionalRanker`
  - [x] Percentile rank per rebalance date
  - [x] Assign quintile labels (Q1 loser → Q5 winner)
  - [x] Unit test: ranks sum to N*(N+1)/2, quintile counts balanced


### 2.6 IC Analysis

- [x] `src/csm/research/ic_analysis.py` — `ICAnalyzer`
  - [x] Pearson IC: corr(signal_t, forward_return_t+1M)
  - [x] Spearman rank IC
  - [x] ICIR = mean(IC) / std(IC)
  - [x] Decay curve: IC at horizons 1M, 2M, 3M, 6M, 12M
  - [x] Unit test: IC against known synthetic data


### 2.7 Signal Research Notebook

- [x] Notebook `02_signal_research.ipynb`
  - [x] IC time series for each signal
  - [x] ICIR table: all signals ranked
  - [x] Signal correlation matrix (check redundancy)
  - [x] Decay curves
  - [x] Quintile return spreads (Q5 − Q1) by year
  - [x] **Decision**: which signals to include in the composite score


**Exit criteria:** at least one signal with ICIR > 0.3 on SET. Composite signal defined and documented.

---

## Phase 3 — Backtesting

> Goal: walk-forward backtest of the composite signal with realistic cost assumptions.

### 3.1 Backtest Engine

- [x] `src/csm/research/backtest.py` — `MomentumBacktest`
  - [x] Monthly rebalance on last trading day of month
  - [x] Survivorship-bias-safe universe (use dated universe snapshots)
  - [x] Transaction cost: 15 bps per side (0.15%) round-trip
  - [x] Position sizing: equal weight by default
  - [x] Output: `BacktestResult` with equity curve, positions history, turnover log
- [x] Pydantic models: `BacktestConfig`, `BacktestResult`
  - [x] `BacktestResult.metrics_dict()` → JSON-serialisable dict (no raw prices)
  - [x] `BacktestResult.equity_curve_dict()` → NAV indexed to 100 (no absolute prices)
  - [x] `BacktestResult.annual_returns_dict()` → year → return float
- [x] Unit test: zero-cost backtest of perfect signal returns correct PnL
- [x] Unit test: transaction cost reduces return by expected amount

### 3.2 Performance Metrics

- [x] `src/csm/risk/metrics.py` — `PerformanceMetrics`
  - [x] CAGR, Sharpe, Sortino, Calmar, Max Drawdown
  - [x] Win rate, avg monthly return, annualised volatility
  - [x] Alpha and Beta vs SET index
- [x] Unit test: Sharpe ratio vs manual calculation

### 3.3 Drawdown Analysis

- [x] `src/csm/risk/drawdown.py` — `DrawdownAnalyzer`
  - [x] Max drawdown, underwater curve, recovery statistics

### 3.4 Backtest Notebook

- [x] Notebook `03_backtest_analysis.ipynb`
  - [x] Equity curve vs SET TRI benchmark
  - [x] Annual return bar chart
  - [x] Rolling Sharpe (12-month window)
  - [x] Drawdown chart
  - [x] Performance table by formation period
  - [x] Sensitivity analysis: top_quantile 10% / 20% / 30%
  - [x] **Decision**: final parameter set

**Exit criteria:** walk-forward CAGR > SET benchmark, Sharpe > 0.5, max drawdown documented.

---

## Phase 4 — Portfolio Construction & Risk

> Goal: production-ready portfolio construction with regime awareness.

### 4.1 Portfolio Construction

- [x] `src/csm/portfolio/construction.py` — `PortfolioConstructor`
  - [x] Top-quintile selection from ranked signal
  - [x] Sector diversification constraint (max 40% in any one sector)
  - [x] Min position size (1% floor), max position size (10% cap)
- [x] Unit test: weight constraints satisfied

### 4.2 Weight Optimizer

- [x] `src/csm/portfolio/optimizer.py` — `WeightOptimizer`
  - [x] Equal weight, vol-target, minimum-variance
- [x] Unit test: all schemes sum to 1.0, no negative weights

### 4.3 Rebalance Scheduler

- [x] `src/csm/portfolio/rebalance.py` — `RebalanceScheduler`
  - [x] Last trading day of month schedule
  - [x] Turnover calculation and trade list output

### 4.4 Regime Detection

- [x] `src/csm/risk/regime.py` — `RegimeDetector`
  - [x] BULL / BEAR / NEUTRAL via 200-day SMA + 3M return
  - [x] BEAR → reduce allocation to 50%
- [x] Unit test: regime transitions on known price series

### 4.5 Portfolio Optimization Notebook

- [x] Notebook `04_portfolio_optimization.ipynb`
  - [x] Equal vs vol-target vs min-variance equity curves
  - [x] Regime-filtered vs unfiltered performance
  - [x] Sector exposure over time, turnover analysis
  - [x] **Decision**: final portfolio construction config

**Exit criteria:** regime filter reduces drawdown in bear periods.

---

## Phase 5 — API

> Goal: FastAPI serving live signals and portfolio via REST, with daily auto-refresh and public mode enforcement.

### 5.1 App Factory & Lifespan

- [x] `api/main.py` — app factory with lifespan, CORS, router mounting
  - [x] Public mode middleware: block write endpoints when `CSM_PUBLIC_MODE=true`
  - [x] CORS middleware: `allow_origins`, `allow_methods`, `allow_headers` configured for future UI projects on different domains/ports
  - [x] Mount `results/notebooks/` as `/static/notebooks/` (StaticFiles)
  - [x] OpenAPI auto-docs at `/docs` (Swagger) and `/redoc` (ReDoc)
- [x] `/health` returns `{"status": "ok", "version": "...", "public_mode": true/false}`
- [x] Request-ID middleware (ULID per request), structured logging with JSON formatter
- [x] RFC 7807 problem-details error handling for all 4xx/5xx responses

### 5.2 Routers & Response Schemas

- [x] `api/schemas/` package — typed Pydantic v2 models for every endpoint
- [x] `api/routers/universe.py` — `GET /api/v1/universe` with ETag support
- [x] `api/routers/signals.py` — `GET /api/v1/signals/latest`
  - [x] Public mode: read from `results/signals/latest_ranking.json`
  - [x] Private mode: compute from live feature matrix
- [x] `api/routers/portfolio.py` — `GET /api/v1/portfolio/current`
  - [x] Public mode: read from `results/backtest/summary.json`
  - [x] Surfaces regime, breaker_state, equity_fraction from Phase 4 modules
- [x] `api/routers/backtest.py` — `POST /api/v1/backtest/run` via JobRegistry (403 in public mode)
- [x] `api/routers/data.py` — `POST /api/v1/data/refresh` via JobRegistry (403 in public mode)
- [x] `api/routers/jobs.py` — `GET /api/v1/jobs/{job_id}` and `GET /api/v1/jobs` for status polling
- [x] `api/routers/notebooks.py` — `GET /api/v1/notebooks` typed index
- [x] `api/routers/scheduler.py` — `POST /api/v1/scheduler/run/{job_id}` manual trigger (private only)
- [x] OpenAPI tags, summaries, descriptions, and examples on every route; snapshot test pinned

### 5.3 Job Lifecycle & Scheduler

- [x] `api/jobs.py` — `JobRegistry` state machine (accepted→running→succeeded|failed|cancelled)
  - [x] Per-kind FIFO queues with dedicated worker tasks
  - [x] Restart-safe: WAL-style JSON persistence under `results/.tmp/jobs/`
  - [x] Orphaned RUNNING jobs marked FAILED on restart
- [x] `api/scheduler/jobs.py` — APScheduler bound to `Settings.refresh_cron` with `misfire_grace_time`
  - [x] Skip all jobs when `public_mode=True`
  - [x] Writes `results/.tmp/last_refresh.json` marker on completion
  - [x] `/health` reflects scheduler status and last_refresh marker
- [x] `scripts/refresh_daily.py` — manual trigger (private only)
- [x] `scripts/export_results.py` — regenerate `results/` for git commit

### 5.4 Authentication & Security

- [x] `api/security.py` — `APIKeyMiddleware` (X-API-Key header)
  - [x] Public mode: always allow (writes already 403'd by public_mode_guard)
  - [x] Private mode with `api_key=None`: log warning, allow all (dev mode)
  - [x] Private mode with key set: 401 on missing/invalid key
  - [x] Constant-time comparison, key redaction in logs
  - [x] Exempt paths: `/health`, `/docs`, `/static/notebooks/*`, read-only GET routes

### 5.5 Observability & Static Serving

- [x] `api/logging.py` — JSON formatter, request-ID contextvar propagation, access log middleware
- [x] `api/errors.py` — RFC 7807 `application/problem+json` for all errors
- [x] `api/static_files.py` — `NotebookStaticFiles` with ETag, Cache-Control, fallback HTML
- [x] `examples/05_api_validation.py` — sign-off script exercising all 12 success criteria

### 5.6 Integration Test Suite

- [x] 12 integration test files covering every (mode × endpoint) pair
- [x] OpenAPI snapshot test with pinned schema
- [x] 742 tests total, 92% line coverage on `api/`
- [x] All quality gates green: ruff, ruff format, mypy, pytest

**Exit criteria:** API starts in public mode with no credentials, read endpoints return results/ data correctly. Write endpoints return 403. Private mode enables full job lifecycle with API-key auth. ✓

---

## Phase 6 — Docker & Public Distribution

> Goal: `git clone` + `docker compose up` → research visible at `localhost:8000`. Zero setup required.

### 6.1 Dockerfile

- [x] `Dockerfile` — multi-stage: builder (`python:3.11-slim` + `uv`) + slim runtime
- [x] Default `ENV CSM_PUBLIC_MODE=true`
- [x] Expose port 8000 (API)
- [x] Docker HEALTHCHECK using `/health` endpoint for container monitoring

### 6.2 Docker Compose

- [x] `docker-compose.yml` — public mode, `results/` mounted read-only
- [x] `docker-compose.private.yml` — owner override with writable volumes
- [x] Test: `docker compose up` from fresh clone with no `.env` → no errors

### 6.3 Export Results Script

- [x] `scripts/export_results.py` — complete and tested
  - [x] Export notebooks to `results/notebooks/*.html`
  - [x] Export `results/backtest/summary.json` — metrics only, no prices
  - [x] Export `results/backtest/equity_curve.json` — NAV indexed to 100
  - [x] Export `results/backtest/annual_returns.json`
  - [x] Export `results/signals/latest_ranking.json` — scores/quintiles only
- [x] JSON Schema sidecars (`.schema.json`) for every export artefact
- [x] Owner workflow: export → `git add results/` → commit → push

### 6.4 Data Boundary Audit

- [x] `results/backtest/equity_curve.json` — NAV only, no absolute prices
- [x] `results/signals/latest_ranking.json` — scores/quintiles only, no OHLCV
- [x] Notebook HTML (`--no-input`) — charts visible, no raw data tables
- [x] `.gitignore` excludes all of `data/` directory
- [x] Two-layer CI audit: file-walk + API response scan for OHLCV leaks

### 6.5 README Rewrite

- [x] Quick Start: `git clone` + `docker compose up` → `localhost:8000`
- [x] Architecture (Headless) section with ASCII + Mermaid diagrams
- [x] "Build your own frontend" section with JSON Schema → TypeScript generation
- [x] Owner workflow section: credentials, private compose, data refresh

### 6.6 CI Smoke Workflow

- [x] `.github/workflows/docker-smoke.yml` — PR-gated `docker compose up --wait`
- [x] Health check + smoke-test 4 read endpoints (200) + 1 write endpoint (403)
- [x] Container log capture + artifact upload on failure

### 6.7 GHCR Image Publishing

- [x] `.github/workflows/docker-publish.yml` — tag-driven (`v*.*.*`) + `workflow_dispatch`
- [x] Multi-tag: `vX.Y.Z`, `vX.Y`, `latest`, `sha-<short>`
- [x] GHA cache (`type=gha`) for fast rebuilds
- [x] `RELEASING.md` — owner runbook for cutting a release

**Exit criteria:** fresh `git clone` + `docker compose up` → all notebook pages load, backtest chart renders, signal rankings visible. Zero errors in container logs. CI smoke green on PRs. GHCR image published and pullable. ✓

---

## Phase 7 — Hardening & Documentation

> Goal: production-ready quality, complete documentation.

### 7.1 Test Coverage

- [x] All unit tests passing
- [x] All integration tests passing (public mode + private mode variants)
- [x] 742 tests, 92% line coverage on `api/`

### 7.2 Documentation

- [x] All `docs/` pages translated and complete (12 stubs)
- [x] `docs/guides/public-mode.md` — data boundaries, Docker, owner workflow
- [x] `README.md` — full, with quick start and badges

### 7.3 API Security

- [x] API key middleware (`X-API-Key` header) protecting private-mode endpoints
- [x] Public mode: read-only enforcement with 403 on write endpoints
- [x] Constant-time key comparison, key redaction in logs

### 7.4 CI

- [x] `.github/workflows/docker-smoke.yml` — PR-gated smoke test on Docker paths
- [x] `.github/workflows/docker-publish.yml` — tag-driven GHCR publish
- [ ] `ci.yml`: lint → type-check → test on every push (general CI beyond Docker)

**Exit criteria:** general `ci.yml` (lint → type-check → test on every push), any remaining doc gaps filled.

---

## Phase 8 — Enhancement (Post-MVP)

> Optional upgrades after Phase 7 is complete.

- [ ] Fundamental filter (P/BV, ROE) via SET SMART
- [ ] Foreign flow signal from SET website
- [ ] LightGBM ranking model
- [ ] Intraday entry timing using 1H data
- [ ] Multi-factor composite: momentum + value + quality

---

## Note: Future Multi-Strategy Dashboard

เนื่องจากต้องการรองรับการทำ Multi-Strategy Aggregation (แสดงผลตอบแทนรวมจากหลายกลยุทธ์) จึงจะแยกส่วน UI ไปพัฒนาเป็นโปรเจกต์ใหม่ที่สามารถเชื่อมต่อกับหลาย API ได้ในภายหลัง

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

## Dependency Map

```
Phase 0 (Bootstrap)
    └── Phase 1 (Data Pipeline)
            └── Phase 2 (Signal Research)
                    └── Phase 3 (Backtesting)
                            └── Phase 4 (Portfolio & Risk)
                                    ├── Phase 5 (API)
                                    │       └── Phase 6 (Docker & Public)
                                    │               └── Phase 7 (Hardening)
                                    └── Phase 8 (Enhancement)
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
| 6     | Docker & Public Distribution | 3–4 days   |
| 7     | Hardening & Docs             | 1 week     |
| 8     | Enhancement (optional)       | open-ended |

**MVP with public distribution (Phase 0–6): ~8–10 weeks**

---

## Current Status

> Update this section as phases complete.

- **Active phase:** Phase 7 — Hardening & Documentation
- **Completed phases:**
  - Phase 0 (Bootstrap) — project scaffold, tooling, quality gates
  - Phase 1 (Data Pipeline) — sub-phases 1.1–1.7 complete as of 2026-04-23
  - Phase 2 (Signal Research) — sub-phases 2.1–2.7 complete
  - Phase 3 (Backtesting) — sub-phases 3.1–3.4 complete
  - Phase 4 (Portfolio Construction & Risk) — sub-phases 4.1–4.5 complete, confirmed by `results/notebooks/04_portfolio_optimization.html`
  - Phase 5 (API) — sub-phases 5.1–5.9 complete as of 2026-05-01: typed FastAPI surface, JobRegistry, API-key auth, RFC 7807 errors, structured logging, 742 tests, 92% coverage, sign-off validated via `examples/05_api_validation.py`
  - Phase 6 (Docker & Public Distribution) — sub-phases 6.1–6.7 complete as of 2026-05-02: multi-stage Dockerfile, dual compose config, export results with JSON Schema, two-layer data boundary audit, README rewrite, CI smoke + GHCR publish workflows, `RELEASING.md`, v0.6.0 GitHub Release published
- **Blocked by:** nothing
