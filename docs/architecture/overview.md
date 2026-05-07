# Architecture Overview

This page describes the overall monorepo structure of csm-set, the separation between the library, API, and UI layers, the runtime data flow, the public-mode enforcement boundary, the security model, and the configuration surface.

## Table of Contents

- [Monorepo layers](#monorepo-layers)
- [Runtime data flow](#runtime-data-flow)
- [Public-mode boundary](#public-mode-boundary)
- [Configuration](#configuration)
- [Security model](#security-model)
- [Timezone policy](#timezone-policy)

---

## Monorepo layers

The project is organised as a layered monorepo. Each layer may import from layers below it, never from layers above it.

### `src/csm/` — Core library

The computational core. Pure Python library with no web framework dependency and no network I/O (all network I/O lives in `scripts/` via `tvkit`). Subpackages:

| Subpackage | Responsibility |
|------------|----------------|
| `src/csm/config/` | Settings (`pydantic-settings`), constants, environment-aware configuration |
| `src/csm/data/` | OHLCV loading via tvkit, Parquet store read/write, universe construction, price cleaning, dividend adjustment |
| `src/csm/features/` | Momentum signal computation, risk-adjusted momentum, sector features, feature pipeline |
| `src/csm/portfolio/` | Weight optimisation, constraints, rebalancing, drawdown circuit breaker, liquidity overlay |
| `src/csm/research/` | Cross-sectional ranking, IC analysis, walk-forward backtest engine |
| `src/csm/risk/` | Risk metrics (Sharpe, Sortino, max drawdown), market regime detection |
| `src/csm/execution/` | Trade-list generation, execution simulation, slippage models |

See [docs/reference/](../reference/) for the full public API surface of each subpackage.

### `api/` — FastAPI surface

The HTTP boundary. Built with FastAPI and uvicorn. Exposes:

- **REST endpoints** under `/api/v1/` — signals, backtest, portfolio, universe, notebooks, jobs, scheduler
- **Health endpoint** at `/health` — service status, version, scheduler state, job count
- **Static files** under `/static/notebooks/` — pre-rendered notebook HTML
- **OpenAPI schema** at `/api/docs` (Swagger) and `/api/redoc` (Redoc)

Key modules:

| Module | Role |
|--------|------|
| `api/main.py` | App factory, lifespan, middleware registration, router mounting |
| `api/security.py` | `X-API-Key` middleware, `public_mode_guard`, constant-time comparison |
| `api/logging.py` | Structured logging, request-id tracing, key redaction |
| `api/routers/` | Per-domain route modules: signals, backtest, portfolio, notebooks, data, jobs, scheduler, universe |
| `api/schemas/` | Pydantic response/request models for all endpoints |
| `api/errors.py` | RFC 7807 problem-detail error handlers |
| `api/jobs.py` | Background job registry with persistence |

### `ui/` — FastUI consumer

Embeds a FastUI dashboard at `/`. This is one consumer of the API — the API and static asset tree are framework-agnostic. Any frontend (React, Next.js, Vue, Flutter) can consume the same endpoints.

### `scripts/` — Owner tooling

Command-line scripts for the private-mode data pipeline:

- `scripts/fetch_history.py` — fetch OHLCV data from TradingView via tvkit
- `scripts/build_universe.py` — build monthly universe snapshots (liquidity, listing filters)
- `scripts/export_results.py` — execute notebooks, generate backtest JSON, produce signal rankings

### `results/static/` — Committed artefacts

Pre-computed, frontend-agnostic outputs committed to git so public users can consume them without running the pipeline:

- `results/static/notebooks/` — nbconvert HTML (code cells stripped)
- `results/static/backtest/` — summary, equity curve, annual returns (JSON + JSON Schema sidecars)
- `results/static/signals/` — latest cross-sectional ranking

### `notebooks/` — Research notebooks

Jupyter notebooks (`.ipynb`) with Thai markdown cells and English code cells:

1. `01_data_exploration.ipynb` — data quality audit
2. `02_signal_research.ipynb` — momentum signal analysis
3. `03_backtest_analysis.ipynb` — walk-forward backtest results
4. `04_portfolio_optimization.ipynb` — portfolio construction analysis

### `tests/` — Test suite

- `tests/unit/` — mirrors `src/csm/` layout; unit tests for each subpackage
- `tests/integration/` — boundary-crossing tests (API, public-mode data boundary, job lifecycle)
- `tests/api/` — API-level tests (middleware, routers, auth)

---

## Runtime data flow

The data pipeline flows top-to-bottom. In public mode, only the bottom layer (`results/static/`) is served — no live pipeline runs.

```
                    ┌────────────────────────────┐
                    │  tvkit (TradingView API)    │  ← Private mode only
                    │  scripts/fetch_history.py   │
                    └────────────┬───────────────┘
                                 │ raw OHLCV
                                 ▼
                    ┌────────────────────────────┐
                    │  data/raw/*.parquet         │
                    └────────────┬───────────────┘
                                 │
                                 ▼
               ┌──────────────────────────────────┐
               │  src/csm/data/                    │
               │  loader.py → Parquet store        │
               │  cleaner.py → dividend adj.        │
               │  universe.py → universe builder   │
               └────────────────┬─────────────────┘
                                │ clean prices, universe
                                ▼
               ┌──────────────────────────────────┐
               │  src/csm/features/                │
               │  momentum.py → log returns        │
               │  risk_adjusted.py → vol-scaled    │
               │  sector.py → sector aggregates    │
               │  pipeline.py → compose all        │
               └────────────────┬─────────────────┘
                                │ feature panel
                                ▼
               ┌──────────────────────────────────┐
               │  src/csm/research/                │
               │  ranking.py → cross-sectional     │
               │  backtest.py → walk-forward       │
               │  ic_analysis.py → IC stats        │
               └────────────────┬─────────────────┘
                                │ rankings, metrics
                                ▼
               ┌──────────────────────────────────┐
               │  src/csm/portfolio/               │
               │  optimizer.py → weights           │
               │  constraints.py → enforce         │
               │  rebalance.py → rebalance engine  │
               └────────────────┬─────────────────┘
                                │ portfolio weights
                                ▼
               ┌──────────────────────────────────┐
               │  results/static/                  │
               │  notebooks/ (HTML)                │
               │  backtest/ (JSON + schema)        │
               │  signals/ (JSON + schema)         │
               └────────────────┬─────────────────┘
                                │ static files + API
                                ▼
               ┌──────────────────────────────────┐
               │  api/                             │
               │  FastAPI → JSON responses         │
               │  /api/v1/*, /static/*, /health    │
               └────────────────┬─────────────────┘
                                │ HTTP :8000
                                ▼
               ┌──────────────────────────────────┐
               │  Client (browser, React, mobile)  │
               └──────────────────────────────────┘
```

### Adapter write-back to quant-infra-db (opt-in)

When `CSM_DB_WRITE_ENABLED=true` and the three DSN env vars are set, the pipeline hooks under `src/csm/adapters/hooks.py` mirror operational time series to the shared `quant-infra-db` stack. The adapters are best-effort: a failure in any single adapter is logged and the pipeline continues, so the write-back path never breaks csm-set's existing local Parquet flow.

```
csm-set → AdapterManager ──▶ PostgresAdapter ──▶ quant-postgres (db_csm_set)
                         │                          • equity_curve
                         │                          • trade_history
                         │                          • backtest_log
                         ├──▶ GatewayAdapter  ──▶ quant-postgres (db_gateway)
                         │                          • daily_performance
                         │                          • portfolio_snapshot
                         └──▶ MongoAdapter    ──▶ quant-mongo    (csm_logs)
                                                    • signal_snapshots
                                                    • backtest_results
                                                    • model_params
```

The same time series are exposed read-only over the private-mode REST surface at `/api/v1/history/*` (six GET endpoints, gated by `X-API-Key`). See [README § Persisting to quant-infra-db](../../README.md#persisting-to-quant-infra-db) for setup and [src/csm/adapters/](../../src/csm/adapters/) for the adapter implementation.

---

## Public-mode boundary

Public mode (`CSM_PUBLIC_MODE=true`) is the default operating mode of the Docker image. It serves pre-computed research without requiring any credentials.

### What public mode enforces

1. **No live data pipeline.** The scheduler is disabled; no tvkit fetches run.
2. **Write endpoints return 403.** Any POST to `/api/v1/data/refresh`, `/api/v1/backtest/run`, `/api/v1/jobs`, or `/api/v1/scheduler/run/*` returns a canonical RFC 7807 response:

   ```json
   {
     "type": "tag:csm-set,2026:problem/public-mode-disabled",
     "title": "Public mode — read only",
     "status": 403,
     "detail": "Disabled in public mode. Set CSM_PUBLIC_MODE=false to enable.",
     "instance": "/api/v1/data/refresh",
     "request_id": "01J..."
   }
   ```

3. **API-key auth is a no-op.** The `APIKeyMiddleware` skips all checks in public mode (read endpoints are already public; writes are already 403'd by `public_mode_guard`).

### Data boundary audit

The public-mode data boundary is verified by two layers of automated tests:

- **File-level audit** (`tests/integration/test_public_data_boundary_files.py`): scans every `.json` file under `results/static/` for OHLCV key patterns (`open`, `high`, `low`, `close`, `volume`, `adj_close`). Any match fails the test.
- **API-level audit** (`tests/integration/test_public_data_boundary_api.py`): hits every GET endpoint and asserts no OHLCV keys appear in any response body.

These tests run as part of `ci.yml` and must pass before merge.

### Private mode

Set `CSM_PUBLIC_MODE=false` to enable the full pipeline. This requires:

- A tvkit installation with TradingView credentials
- `CSM_API_KEY` set for write-endpoint protection
- Writable mounts for `data/` and `results/` (in Docker: `docker-compose.private.yml`)

See [docs/guides/public-mode.md](../guides/public-mode.md) for the full owner workflow and mode-switching instructions.

---

## Configuration

All runtime configuration is driven by environment variables with the `CSM_` prefix, loaded through `pydantic-settings` in `src/csm/config/settings.py`.

### Key environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CSM_PUBLIC_MODE` | `false` | When `true`, disables all write endpoints and the scheduler |
| `CSM_API_KEY` | (none) | Shared secret for `X-API-Key` auth on protected endpoints; `None` disables auth (dev-only) |
| `CSM_CORS_ALLOW_ORIGINS` | `*` | Comma-separated CORS origins; `*` in public mode, restrict in private |
| `CSM_LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `CSM_API_HOST` | `0.0.0.0` | uvicorn bind address |
| `CSM_API_PORT` | `8000` | uvicorn bind port |
| `CSM_DATA_DIR` | `./data` | Base directory for raw/processed market data |
| `CSM_RESULTS_DIR` | `./results` | Directory for pre-computed outputs |
| `CSM_TVKIT_ADJUSTMENT` | `dividends` | Price adjustment mode: `dividends` (total-return) or `splits` |
| `CSM_REFRESH_CRON` | `0 18 * * 1-5` | Cron expression for owner-side scheduled refresh |

### Configuration priority

1. Environment variables (highest)
2. `.env` file in the project root
3. Defaults in `Settings` class (lowest)

The `Settings` singleton is cached via `@lru_cache` and accessed throughout the codebase as `from csm.config.settings import settings`. Test fixtures may patch `sys.modules['csm.config.settings'].settings` to override configuration without touching the environment.

---

## Security model

The middleware chain processes every request in this order (outermost to innermost):

```
RequestIDMiddleware → AccessLogMiddleware → APIKeyMiddleware →
       public_mode_guard → CORSMiddleware → Routers
```

### Middleware responsibilities

| Middleware | Role | Defined in |
|------------|------|------------|
| `RequestIDMiddleware` | Assigns a ULID request-id to every request via a contextvar; available to all downstream layers | `api/logging.py` |
| `AccessLogMiddleware` | Emits structured access logs with request-id, method, path, status, duration | `api/logging.py` |
| `APIKeyMiddleware` | Enforces `X-API-Key` on protected paths in private mode; no-op in public mode or when `api_key` is unset | `api/security.py` |
| `public_mode_guard` | Blocks write endpoints in public mode before they reach routers | `api/main.py` |
| `CORSMiddleware` | Sets CORS headers based on `CSM_CORS_ALLOW_ORIGINS` | Starlette built-in |

### Authentication (`X-API-Key`)

The `APIKeyMiddleware` in `api/security.py` protects write endpoints in private mode:

- **Protected paths:** `/api/v1/data/refresh`, `/api/v1/backtest/run`, `/api/v1/jobs`, `/api/v1/scheduler/run/daily_refresh`
- **Defence in depth:** any non-GET request to `/api/v1/*` is also protected, even if not in the explicit `PROTECTED_PATHS` set
- **Constant-time comparison:** `secrets.compare_digest` prevents timing side-channel attacks on the key
- **Key redaction:** the configured key is never logged; `api/logging.py:install_key_redaction` adds a logging filter that replaces the key with `[REDACTED]` in all log output
- **Startup warning:** if `public_mode=false` and `api_key` is `None`, the lifespan emits a `WARNING` log encouraging the operator to set `CSM_API_KEY`

### Error response shapes

**401 (missing or invalid API key):**
```json
{
  "type": "tag:csm-set,2026:problem/missing-api-key",
  "title": "Missing API key",
  "status": 401,
  "detail": "Missing X-API-Key header.",
  "instance": null,
  "request_id": "01J..."
}
```

**403 (public-mode write block):**
```json
{
  "type": "tag:csm-set,2026:problem/public-mode-disabled",
  "title": "Public mode — read only",
  "status": 403,
  "detail": "Disabled in public mode. Set CSM_PUBLIC_MODE=false to enable.",
  "instance": "/api/v1/data/refresh",
  "request_id": "01J..."
}
```

Both responses include a `request_id` for correlation between client errors and server logs. The 401 response never echoes the supplied key.

For operational instructions (generating keys, configuring auth, testing), see [docs/guides/public-mode.md](../guides/public-mode.md) § Configuring API Key.

---

## Timezone policy

- **Internal storage:** all `pandas.Timestamp` values are timezone-aware UTC.
- **Display/conversion:** values are converted to `Asia/Bangkok` (UTC+7) only at I/O boundaries (API responses, notebook rendering, log messages).
- **Trading calendar:** the SET trading calendar uses Thai business days; tvkit handles the holiday calendar internally. The momentum computation in `src/csm/features/momentum.py` uses trading-day offsets (252, 126, 63, 21) rather than calendar-day offsets, which correctly handles SET public holidays without needing a separate calendar file.

This policy is enforced by convention (documented in `.claude/knowledge/project-skill.md`) rather than by a runtime check.
