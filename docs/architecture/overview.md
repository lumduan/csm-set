# Architecture Overview

This page describes the monorepo structure of csm-set, the separation between the library, API, and UI layers, runtime data flow, public-mode enforcement, configuration, the security model, and timezone policy.

## Monorepo layers

csm-set is a layered monorepo. Each layer imports only from layers *below* it:

```
┌──────────────────────────────────────┐
│ scripts/                             │  Owner tooling (fetch, export, build)
│   imports: src/csm/                  │
├──────────────────────────────────────┤
│ ui/                                  │  FastUI dashboard (mounted on FastAPI)
│   imports: src/csm/, api/            │
├──────────────────────────────────────┤
│ api/                                 │  FastAPI surface (routers, middleware)
│   imports: src/csm/                  │
├──────────────────────────────────────┤
│ src/csm/                             │  Core library (headless, no HTTP)
│   imports: stdlib, third-party only  │
└──────────────────────────────────────┘
```

### `src/csm/` — Core library

The headless library. All quantitative logic lives here: data loading, feature computation, portfolio construction, backtesting, risk metrics, and execution simulation. The library is async at I/O boundaries (data fetching via `httpx.AsyncClient`) and synchronous inside compute-heavy paths. It is importable without a running server and has no dependency on FastAPI, NiceGUI, or any web framework.

Subpackage map:

| Subpackage | Responsibility |
|------------|---------------|
| `csm.config` | `Settings` (pydantic-settings), strategy constants |
| `csm.data` | OHLCV loading (tvkit + parquet), universe construction, price cleaning, symbol filtering |
| `csm.features` | Momentum, risk-adjusted, sector-relative feature computation |
| `csm.portfolio` | Weight optimisation, constraints, rebalancing, circuit breakers, volatility scaling |
| `csm.research` | Cross-sectional ranking, IC analysis, walk-forward backtest |
| `csm.risk` | Drawdown, Sharpe/Sortino, regime detection |
| `csm.execution` | Trade simulation, slippage models, trade list generation |

### `api/` — FastAPI surface

The REST API layer. Mounts routers under `/api/v1/` for signals, backtest, portfolio, data, notebooks, universe, jobs, and scheduler. Applies middleware in order: CORS → request-id → API-key auth → public-mode guard → router. Serves static files from `results/static/` under `/static/`. The OpenAPI schema is auto-generated at `/api/docs`.

### `ui/` — FastUI dashboard

NiceGUI/FastUI views mounted at `/` on the FastAPI app. Consumes the same `/api/v1/` endpoints as any external client. This is one consumer of the API, not the canonical view — the API is framework-agnostic.

### `scripts/` — Owner tooling

Standalone CLI scripts for private-mode operators: `fetch_history.py`, `build_universe.py`, `export_results.py`. These scripts call `src/csm/` directly and write committed artefacts to `results/static/`.

### `results/` — Committed research artefacts

Static JSON and HTML files committed to git. Every `.json` file carries `"schema_version": "1.0"` and a sibling `.schema.json`. These are served read-only in public mode.

---

## Runtime data flow

```
tvkit (TradingView, private only)
    │
    ▼
data/raw/{symbol}.parquet
    │
    ▼
csm.data.loader.OHLCVLoader  ──►  csm.data.cleaner.PriceCleaner
    │                                    │
    ▼                                    ▼
csm.data.store.ParquetStore      csm.data.universe.UniverseBuilder
    │
    ▼
csm.features.MomentumFeatures / RiskAdjustedFeatures / FeaturePipeline
    │
    ▼
csm.research.CrossSectionalRanker  ──►  csm.research.ICAnalyzer
    │
    ▼
csm.research.MomentumBacktest  ──►  csm.risk.PerformanceMetrics
    │
    ▼
csm.portfolio.WeightOptimizer  ──►  csm.portfolio.RebalanceScheduler
    │
    ▼
csm.execution.ExecutionSimulator  ──►  csm.risk.DrawdownAnalyzer
    │
    ▼
results/static/notebooks/   (nbconvert HTML)
results/static/backtest/    (summary.json, equity_curve.json, annual_returns.json)
results/static/signals/     (latest_ranking.json)
    │
    ▼
api/  ──►  /api/v1/signals/latest  (JSON)
            /api/v1/backtest/summary  (JSON)
            /static/notebooks/...    (HTML)
            /api/docs                (OpenAPI)
    │
    ▼
Client (browser, React, mobile, third-party dashboard)
```

**Key rules:**
- Raw OHLCV data never leaves `data/raw/` via the API. Public responses contain derived metrics (z-scores, quintiles, NAV) only.
- All intermediate outputs use `pandas.Timestamp` in UTC internally; display is in `Asia/Bangkok`.
- `results/static/` is the single source of truth for public artefacts. The API reads from it directly in public mode.

---

## Public-mode boundary

Public mode (`CSM_PUBLIC_MODE=true`) is a read-only operating mode for distributing research without credentials. It is enforced at two layers:

### Layer 1 — File-level audit

`results/static/**/*.json` files are audited for OHLCV keys (`open`, `high`, `low`, `close`, `volume`, `adj_close`). The audit runs as part of the test suite (`tests/integration/test_public_data_boundary_*.py`) and blocks commit if any raw price field leaks into committed JSON. Only derived fields (NAV, z-score, quintile, rank percentile, CAGR, Sharpe, drawdown) appear in committed artefacts.

### Layer 2 — API-level audit

The `public_mode_guard` in `api/security.py` blocks all write endpoints in public mode. Any POST/PUT/PATCH/DELETE to `/api/v1/*` returns `403` with a canonical body: `{"detail": "Disabled in public mode"}`. Read endpoints (`GET`) continue to serve from `results/static/` and the in-memory job store.

The full list of protected write paths:
- `/api/v1/data/refresh`
- `/api/v1/backtest/run`
- `/api/v1/jobs`
- `/api/v1/scheduler/run/daily_refresh`

Additionally, any non-GET method on `/api/v1/*` is auto-protected by `is_protected_path()` in `api/security.py` — defence-in-depth for future endpoints.

---

## Configuration

All runtime configuration flows through `src/csm/config/settings.py` using `pydantic-settings`. Environment variables are prefixed with `CSM_` and loaded from `.env` (gitignored). The settings instance is a frozen singleton (via `@lru_cache`) accessible as `csm.config.settings.settings`.

Key variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `CSM_PUBLIC_MODE` | `false` | Set `true` to enable read-only public mode |
| `CSM_API_KEY` | `None` | Shared secret for `X-API-Key` auth on protected endpoints. `None` disables auth (dev-only). |
| `CSM_CORS_ALLOW_ORIGINS` | `*` | Comma-separated CORS origins. Public mode defaults to `*`; restrict in private mode. |
| `CSM_LOG_LEVEL` | `INFO` | Application log level |
| `CSM_DATA_DIR` | `./data` | Base directory for raw/processed market data |
| `CSM_RESULTS_DIR` | `./results` | Directory for pre-computed static artefacts |

See `.env.example` for the full template.

---

## Security model

The middleware chain on every request is:

```
Incoming request
    │
    ▼
CORS middleware     — applies CORS headers based on CSM_CORS_ALLOW_ORIGINS
    │
    ▼
Request-ID          — attaches a ULID request_id to every request (via contextvar)
    │
    ▼
API-key auth        — validates X-API-Key header for protected paths in private mode
    │                 (api.security.APIKeyMiddleware)
    ▼
Public-mode guard   — blocks write endpoints with 403 in public mode
    │                 (api.security.public_mode_guard)
    ▼
Router              — dispatches to the matched route handler
```

**Auth behaviour matrix** (from `api/security.py`):

| Mode | api_key configured | Path protected? | Behaviour |
|------|-------------------|-----------------|-----------|
| Public | — | — | Pass through (writes already 403'd by guard) |
| Private | `None` | — | Pass through (dev mode; WARNING at startup) |
| Private | Set | No | Pass through |
| Private | Set | Yes + missing header | 401 "Missing X-API-Key header" |
| Private | Set | Yes + wrong header | 401 "Invalid X-API-Key header" |
| Private | Set | Yes + correct header | Pass through |

Key implementation details:
- **Constant-time comparison**: `secrets.compare_digest(supplied, configured)` — prevents timing side-channel attacks.
- **Key redaction**: The configured API key is redacted in logs via a logging filter (`api.logging.install_key_redaction`).
- **Startup warning**: If `CSM_PUBLIC_MODE=false` and `CSM_API_KEY` is unset, the server logs a WARNING at startup.
- **Request-ID correlation**: Every auth failure response includes the request's ULID for log correlation.
- **RFC 7807 errors**: 401 responses use `Content-Type: application/problem+json` with `type`, `title`, `status`, `detail`, `request_id` fields.

---

## Timezone policy

| Context | Timezone |
|---------|----------|
| Internal storage (`pandas.Timestamp` in DataFrames/Parquet) | **UTC** |
| Display (API responses, notebook renderings, log timestamps) | **Asia/Bangkok** (UTC+7) |
| Cron schedules (`refresh_cron`) | **Asia/Bangkok** local time |
| Market data timestamps (SET trading hours) | **Asia/Bangkok** |

All financial timestamps are stored as tz-aware `pandas.Timestamp` in UTC and converted to `Asia/Bangkok` at the display boundary. This avoids DST ambiguity and ensures timezone-correct comparisons across data sources.

---

## Cross-references

- [Public Mode Guide](../guides/public-mode.md) — operational details for public and private deployments
- [Development Guide](../development/overview.md) — contributor workflow and quality gate
- [Module Reference: Config](../reference/data/overview.md) — `Settings` and constants
- [Phase 6 Docker Plan](../plans/phase_6_docker/PLAN.md) — public-mode design rationale
- [Phase 5 API Plan](../plans/phase_5_fastapi/PLAN.md) — API layer design
- [api/security.py](../../api/security.py) — auth middleware implementation
- [src/csm/config/settings.py](../../src/csm/config/settings.py) — settings model
