# Phase 6 — Docker & Public Distribution Master Plan

**Feature:** Public Docker distribution — zero-credential `docker compose up` for csm-set, with API-as-Single-Source-of-Truth contract for any present or future frontend
**Branch:** `feature/phase-6-docker`
**Created:** 2026-05-01
**Status:** In Progress
**Depends on:** Phase 1 (Data Pipeline — complete), Phase 2 (Signal Research — complete), Phase 3 (Backtesting — complete), Phase 4 (Portfolio Construction & Risk — complete through 4.9), Phase 5 (FastAPI + FastUI — complete 2026-05-01)
**Positioning:** Distribution layer — wraps the validated Phase 5 API/UI in a multi-stage Docker image, layers a writable owner profile, ships a generic frontend-agnostic JSON data contract, and adds CI smoke-testing + GHCR image publishing. Satisfies the public-mode data-boundary contract from `PUBLIC_MODE_ARCHITECTURE.md` and unblocks the README "Quick Start" promise. Deliberately frees the project from any single frontend (FastUI today, React/Next.js tomorrow) by making port 8000 the canonical Data Engine API.

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

Phase 6 delivers a **zero-setup public distribution** of csm-set: a fresh visitor with Docker installed should be able to run

```bash
git clone https://github.com/lumduan/csm-set
cd csm-set
docker compose up
```

and immediately browse research output (notebooks, backtest equity curve, signal rankings) at `http://localhost:8000` — **without** a TradingView account, an `.env` file, or any market-data fetch.

It also closes the public-mode loop architected in [PUBLIC_MODE_ARCHITECTURE.md](../PUBLIC_MODE_ARCHITECTURE.md): pre-computed JSON / HTML artefacts are committed to git, the API serves them in public mode, write endpoints return 403, and the owner refreshes them through a documented script. Phase 6 is the execution of that design — every architectural decision was made in earlier phases; what remains is hardening, tooling, and documentation.

### Scope

Phase 6 covers seven sub-phases. The first five (6.1–6.5) implement ROADMAP §Phase 6 verbatim; the latter two (6.6–6.7) are user-directed extensions that bring CI and image distribution forward from Phase 7 to harden the public release sooner.

| Sub-phase | Deliverable | Purpose |
|---|---|---|
| 6.1 | Multi-stage Dockerfile + `.dockerignore` + CORS middleware | Production-grade image; API as the entrypoint, headless-ready |
| 6.2 | Public + private `docker-compose` configs | One-command public boot; owner override for fetch + export |
| 6.3 | `scripts/export_results.py` | Generic frontend-agnostic JSON contract + JSON Schema sidecars |
| 6.4 | Two-layer data boundary audit (file + API) | Guarantee no OHLCV leaks via static files **or** API responses |
| 6.5 | README rewrite | Quick Start + Architecture (Headless) + owner workflow + TS types |
| 6.6 | `.github/workflows/docker-smoke.yml` | PR-gated `docker compose up` + endpoint smoke test |
| 6.7 | `.github/workflows/docker-publish.yml` | Tag-driven build + push to `ghcr.io/lumduan/csm-set` |

### Out of Scope

- **Multi-arch builds** (`linux/arm64` for Apple Silicon hosts) — deferred; AMD64 only in 6.7
- **Kubernetes / Helm** manifests — deferred to a future ops phase
- **Hot-reload `docker-compose.dev.yml`** — local `uv run` covers the dev loop
- **Image signing (cosign / Sigstore) and SBOM generation** — Phase 7 hardening
- **Vulnerability scanning (trivy) gating** — Phase 7 hardening
- **A separate React/Next.js front-end container** — only the *path* is laid (Frontend Transition section); no React code lands in this phase

---

## Problem Statement

Three concrete gaps separate the project from a public release:

1. **The Dockerfile is a stub.** It builds, but the entrypoint runs the standalone NiceGUI dashboard (`uv run python ui/main.py`) rather than the FastAPI app, has no HEALTHCHECK, no `.dockerignore` (so the build context includes `data/`, `tests/`, `.git/`, raw notebooks), exposes both 8000 and 8080 redundantly, and is single-stage (image > 600 MB). It also lacks any CORS configuration, so a future React app on Vercel calling port 8000 would be blocked by the browser at first load.
2. **The artefact pipeline is missing.** `PUBLIC_MODE_ARCHITECTURE.md` specifies `results/static/{notebooks,backtest,signals}/` as the public-mode data source, and Phase 5's API reads from there in public mode — but the script that populates those files (`scripts/export_results.py`) does not exist. Without it, `docker compose up` would boot to an empty UI.
3. **The README has no public on-ramp.** A first-time visitor sees a development-oriented README with `uv sync` instructions but no `docker compose up` block, no "what you'll see," and no signal that this project's port 8000 is a frontend-agnostic Data Engine they can build their own dashboard on top of.

A fourth, more subtle problem: **there is no automated guarantee** that future PRs won't break the public bootstrap. Phase 6.6 (CI smoke workflow) closes that gap so "the public release works" becomes a CI invariant rather than a hope.

---

## Design Rationale

### API as Single Source of Truth (Headless-First)

The defining architectural choice in this phase is that **port 8000 is the project's primary API gateway** — the Data Engine. FastUI is one consumer of that API mounted on the same FastAPI app for convenience; it is not the entrypoint and not the only future client. The container `CMD` boots `uvicorn api.main:app`, never `ui/main.py`. This decoupling is the foundation that lets the Phase 6.3 JSON artefacts double as a generic data contract, and it is what makes the project framework-agnostic.

```
                     ┌──────────────────────────┐
                     │  CSM-SET Container       │
                     │  port 8000  uvicorn      │
                     │  ┌────────────────────┐  │
                     │  │  FastAPI app       │  │
                     │  │   /api/v1/...      │  │◄───── React / Next.js (future)
                     │  │   /static/...      │  │◄───── Mobile app (future)
                     │  │   /                 │  │◄───── Third-party dashboard
                     │  │   (FastUI mount)   │  │◄───── FastUI (today, embedded)
                     │  └────────────────────┘  │
                     │  results/static/         │
                     │   ├── notebooks/         │
                     │   ├── backtest/          │
                     │   └── signals/           │
                     └──────────────────────────┘
```

### Frontend Transition Path

- *Today* — FastUI ships embedded, mounted on the FastAPI app. Zero Node dependency. Anyone running `docker compose up` sees a working dashboard.
- *Tomorrow* — `results/static/` (produced by 6.3) is already a flat static-asset tree. An Nginx container can `root /app/results/static/` directly with no transformation; a React/Next.js front-end can `fetch('/api/v1/signals/latest')` and `fetch('/static/backtest/summary.json')` without backend changes. The JSON Schema sidecars (`*.schema.json`) feed `npx json-schema-to-typescript` for type-safe React/TypeScript development.
- *Migration* — moving to React adds a new front-end container talking to port 8000. The API container is unchanged. CORS is already configured (6.1) so the cross-origin dev loop just works.

### Generic / Frontend-Agnostic JSON Contract

Every artefact under `results/static/` is validated by a Pydantic model in `scripts/export_results.py` and carries a top-level `"schema_version": "1.0"` field. The corresponding `*.schema.json` sidecar (JSON Schema draft-2020-12, generated via `MyModel.model_json_schema()`) lets any client — React, Vue, Flutter, an external researcher's notebook — auto-generate types without coupling to Python.

### Multi-Stage Build (User-Directed Extension)

ROADMAP §6.1 lists "single image" but does not mandate single-stage. Phase 6.1 uses a builder stage (`python:3.11-slim` + uv) that runs `uv sync --frozen --no-dev` into `/opt/venv`, and a slim runtime stage that copies only the venv. This drops the runtime image by ~150–200 MB and removes the uv binary from the final image (smaller attack surface, no unused build tools shipping to users). Build cache layering keeps incremental builds fast.

### Public CI Smoke Workflow (User-Directed Extension)

ROADMAP defers CI to Phase 7, but the user opted to bring it forward. `.github/workflows/docker-smoke.yml` runs `docker compose up -d --wait`, asserts `/health` and three representative endpoints return 200, uploads `docker compose logs` on failure, and tears down. This makes "the public release works" a per-PR invariant rather than a manual sanity check. Keeping smoke-only (not full integration) holds the workflow under 5 min wall-clock.

### GHCR Image Publishing (User-Directed Extension)

Tag-driven (`v*.*.*`) builds push to `ghcr.io/lumduan/csm-set:{vX.Y.Z, vX.Y, latest, sha-…}`. Public users skip the build step entirely with `docker pull`. AMD64 only for Phase 6; arm64 deferred to keep the publish workflow single-platform and fast.

### Public-by-Default, No Secrets in Image

`ENV CSM_PUBLIC_MODE=true` is baked into the image. Private mode is toggled exclusively by `docker-compose.private.yml` overrides on the owner's machine. **No tvkit credentials, no `.env`, no Chrome profile** ever lives in the image. The owner mounts those at runtime.

### HEALTHCHECK Wired to Phase 5's `/health`

Phase 5.8 ships an extended `/health` endpoint that reports DB / results-mount / scheduler state. Phase 6.1 wires Docker HEALTHCHECK directly to it (`curl -f http://localhost:8000/health || exit 1`, interval 30s, retries 3, start-period 20s). Combined with `restart: unless-stopped` in compose, a container that loses its results mount or wedges on startup self-recovers.

### nbconvert with Explicit Timeout & Memory Budget

`jupyter nbconvert --to html --execute --no-input --ExecutePreprocessor.timeout=600` is used for notebook export. `--no-input` keeps OHLCV cells out of the rendered HTML; the explicit 600 s timeout prevents hung kernels from blocking CI. The export script measures peak memory via `resource.getrusage()` after each notebook so users can right-size limits; the heaviest notebook (`04_portfolio_optimization`) is documented at ~2 GB peak.

### CORS Now, Not Later

Adding `CORSMiddleware` in 6.1 (one-line patch in `api/main.py`) anticipates a future React/Next.js front-end on port 3000 or Vercel calling port 8000. Doing it now is essentially free; doing it later means rolling another release just to unblock frontend work.

---

## Architecture

### File Map

```
.
├── Dockerfile                                  # MODIFY — multi-stage, HEALTHCHECK, CMD=uvicorn, port 8000
├── .dockerignore                               # NEW — exclude data/, tests/, .git/, __pycache__/, .venv/, *.parquet, notebooks/
├── docker-compose.yml                          # MODIFY — port 8000 only, healthcheck stanza, mem_limit: 2g
├── docker-compose.private.yml                  # NEW — owner override, writable mounts, tvkit env
├── .gitignore                                  # MODIFY — data/raw|processed|universe, .env*, results/.tmp/
├── README.md                                   # REWRITE — Quick Start, Architecture (Headless), owner workflow, TS types
├── api/
│   └── main.py                                 # MODIFY — add CORSMiddleware (env-driven origins)
├── scripts/
│   ├── _export_models.py                       # NEW — Pydantic models for all distribution payloads
│   └── export_results.py                       # NEW — async exporter: notebooks → HTML, backtest+signals → JSON + .schema.json
├── results/
│   └── static/                                 # NEW root for frontend-agnostic artefacts
│       ├── notebooks/                          # nbconvert HTML output (4 files)
│       ├── backtest/
│       │   ├── summary.json + summary.schema.json
│       │   ├── equity_curve.json + equity_curve.schema.json
│       │   └── annual_returns.json + annual_returns.schema.json
│       └── signals/
│           └── latest_ranking.json + latest_ranking.schema.json
├── tests/
│   └── integration/
│       ├── test_cors.py                        # NEW — OPTIONS preflight returns Access-Control-Allow-* headers
│       ├── test_public_data_boundary_files.py  # NEW — walks results/static/**, fails on OHLCV keys
│       ├── test_public_data_boundary_api.py    # NEW — TestClient hits public read endpoints, scans for OHLCV leak
│       └── test_export_results.py              # NEW — exporter idempotency, schema/JSON match
└── .github/
    └── workflows/
        ├── docker-smoke.yml                    # NEW (6.6) — PR + main: compose up + curl + assertions
        └── docker-publish.yml                  # NEW (6.7) — tag v*.*.*: build + push to GHCR
```

### Boot Sequence (Public)

```
git clone csm-set
        ↓
docker compose up
        ↓
[builder stage] uv sync --frozen --no-dev → /opt/venv
        ↓
[runtime stage] copy venv + src/ + api/ + ui/ + results/
        ↓
container start → uvicorn api.main:app on :8000
        ↓
HEALTHCHECK polls /health → reports healthy after start-period
        ↓
user opens http://localhost:8000
        ↓
api.main:app serves /api/v1/*, /static/*, FastUI mount at /
```

### Boot Sequence (Owner / Private)

```
docker compose -f docker-compose.yml -f docker-compose.private.yml up
        ↓
override applies CSM_PUBLIC_MODE=false, TVKIT_BROWSER=chrome, writable data/+results/
        ↓
owner exec into container or run host-side:
        ↓
uv run python scripts/fetch_history.py        # tvkit → data/raw/
uv run python scripts/export_results.py       # notebooks → HTML, backtest+signals → JSON
        ↓
git add results/static/ && git commit && git push
        ↓
public users get fresh research on next image rebuild / git pull
```

### Data Flow (Public Mode)

```
Browser ─▶ :8000 /api/v1/signals/latest ─▶ public_mode middleware ─▶ reads results/static/signals/latest_ranking.json ─▶ JSON to client
        ─▶ :8000 /static/backtest/summary.json ─▶ FastAPI StaticFiles mount ─▶ raw JSON to client (frontend-agnostic)
        ─▶ :8000 /static/notebooks/01_data_exploration.html ─▶ static HTML iframe in FastUI / direct fetch in React
```

---

## Implementation Phases

### Phase 6.1 — Multi-Stage Dockerfile + API Runtime Hardening

**Status:** `[ ]` Pending
**Goal:** Replace the stub Dockerfile with a production-grade multi-stage build whose entrypoint is the FastAPI app on port 8000. Add CORS middleware to unblock future frontends.

**Deliverables:**

- [ ] `Dockerfile` rewrite:
  - **Builder stage:** `FROM python:3.11-slim AS builder`; copy `uv` from `ghcr.io/astral-sh/uv:latest`; copy `pyproject.toml uv.lock`; `RUN uv sync --frozen --no-dev` into `/opt/venv`
  - **Runtime stage:** `FROM python:3.11-slim`; install `curl` (for HEALTHCHECK); copy `/opt/venv` from builder; copy `src/ api/ ui/ results/`
  - `ENV CSM_PUBLIC_MODE=true PYTHONPATH=/app/src VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1`
  - `HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD curl -f http://localhost:8000/health || exit 1`
  - `EXPOSE 8000`
  - `CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]`
- [ ] `.dockerignore` (NEW) excluding: `data/ tests/ .git/ .github/ __pycache__/ .venv/ .pytest_cache/ .mypy_cache/ .ruff_cache/ *.parquet *.ipynb_checkpoints results/.tmp/ notebooks/ docs/ .env .env.* htmlcov/`
- [ ] `api/main.py` patch — add `CORSMiddleware`:
  - `allow_origins` driven by `CSM_CORS_ALLOW_ORIGINS` env var (comma-separated); defaults to `["*"]` in public mode, restricted to `localhost:3000,localhost:5173` in private mode
  - `allow_methods=["GET","POST","OPTIONS"]`; `allow_headers=["*"]`; `allow_credentials=False` (no cookies in public read-only API)
- [ ] `tests/integration/test_cors.py` (NEW): `OPTIONS /api/v1/signals/latest` returns 200 with `access-control-allow-origin` and `access-control-allow-methods` headers; `GET /api/v1/signals/latest` from a non-allowed origin in private mode is rejected at preflight
- [ ] `Settings` extension in `src/csm/config/settings.py` — add `cors_allow_origins: list[str]` field parsed from env (Pydantic `field_validator` splitting on `,`)

**Acceptance Criteria:**

- `docker build -t csm-set:test .` succeeds; image size < 400 MB compressed (`docker image ls --format "{{.Size}}"`)
- `docker run --rm -p 8000:8000 csm-set:test` boots in < 15 s and `curl -f localhost:8000/health` returns 200
- `docker inspect --format='{{.State.Health.Status}}' <id>` reports `healthy` within 60 s
- `tests/integration/test_cors.py` passes; quality gate green

---

### Phase 6.2 — Docker Compose Dual Config

**Status:** `[ ]` Pending
**Goal:** Public users get a one-command boot; the owner gets a writable override profile that mounts data/, results/, and tvkit auth without baking secrets into the image.

**Deliverables:**

- [ ] `docker-compose.yml` rewrite:
  - Service `csm`: `build: .`; single port `"8000:8000"`; `environment: { CSM_PUBLIC_MODE: "true", CSM_LOG_LEVEL: "INFO" }`
  - `volumes: [ "./results:/app/results:ro" ]`
  - `healthcheck` reflecting Dockerfile (interval 30s, retries 3)
  - `mem_limit: 2g` (matches nbconvert documented budget; harmless for read-only public boot)
  - `restart: unless-stopped`
- [ ] `docker-compose.private.yml` (NEW) — override-only, no service redefinition:
  - `environment: { CSM_PUBLIC_MODE: "false", TVKIT_BROWSER: "chrome", CSM_CORS_ALLOW_ORIGINS: "http://localhost:3000,http://localhost:5173" }`
  - `volumes: [ "./data:/app/data", "./results:/app/results", "~/.config/google-chrome:/root/.config/google-chrome:ro" ]` (owner overrides `:ro` and adds writable data + chrome auth)
  - File header comment block documenting the invocation: `docker compose -f docker-compose.yml -f docker-compose.private.yml up`
- [ ] Smoke command for the public path documented in `docker-compose.yml` header

**Acceptance Criteria:**

- `docker compose up -d` from a fresh clone (no `.env`) boots cleanly with no ERROR-level logs in 30 s
- `docker compose -f docker-compose.yml -f docker-compose.private.yml up` boots with private flags applied (`docker exec csm env | grep CSM_PUBLIC_MODE` shows `false`)
- `results/` is mounted read-only in public, read-write in private (writes from `export_results.py` succeed in private and fail in public)

---

### Phase 6.3 — Export Results Script (Generic Data Contract)

**Status:** `[ ]` Pending
**Goal:** A single owner-runnable script that produces the entire frontend-agnostic distribution payload — HTML notebooks, JSON metrics, and JSON Schema sidecars — under `results/static/`.

**Deliverables:**

- [ ] `scripts/_export_models.py` (NEW) — Pydantic models for every payload:
  - `BacktestSummary` (schema_version, generated_at, period, config, metrics) — schema mirrors PUBLIC_MODE_ARCHITECTURE.md exactly
  - `EquityCurve` (schema_version, description, series: list of `{date, nav, benchmark_nav}`)
  - `AnnualReturns` (schema_version, rows: list of `{year, portfolio_return, benchmark_return}`)
  - `SignalRanking` (schema_version, as_of, description, rankings: list of `{symbol, sector, quintile, z_score, rank_pct}`)
  - `ExportResultsConfig` (notebook_dir, output_dir, execute, timeout_s, memory_budget_mb, only_notebooks, only_backtest, only_signals)
- [ ] `scripts/export_results.py` (NEW):
  - Module-level logger via `logging.getLogger(__name__)`; structured JSON formatter for CI parsability
  - `async def export_notebooks(config) -> None` — `subprocess.run(["jupyter","nbconvert","--to","html","--execute","--no-input","--ExecutePreprocessor.timeout=600","--ExecutePreprocessor.kernel_name=python3","--output-dir",str(out_dir),str(nb)])`; logs `resource.getrusage(RUSAGE_CHILDREN).ru_maxrss` after each notebook
  - `async def export_backtest(config) -> None` — uses `MomentumBacktest` + `BacktestConfig` from Phase 4; validates output through `BacktestSummary`/`EquityCurve`/`AnnualReturns` before write
  - `async def export_signals(config) -> None` — uses `FeaturePipeline` + `CrossSectionalRanker`; validates through `SignalRanking`
  - **Schema sidecar emission:** for each `<name>.json`, also write `<name>.schema.json` containing `Model.model_json_schema()` (JSON Schema draft-2020-12)
  - CLI: `argparse` with `--notebooks-only|--backtest-only|--signals-only|--skip-notebooks` mutually exclusive flags; default = run all three
  - **Idempotency:** sort dict keys, format with `indent=2, ensure_ascii=False`; `generated_at` is the only field that changes between runs
  - All HTTP I/O (none expected, but if added) uses `httpx.AsyncClient` per project standard
- [ ] `tests/integration/test_export_results.py` (NEW):
  - `test_idempotent` — run twice, assert byte-identical JSON except `generated_at`
  - `test_schema_matches_data` — load each `<name>.json`, validate against the sibling `<name>.schema.json` (using `jsonschema` library)
  - `test_notebook_html_no_input` — run on a tiny fixture notebook with a "secret OHLCV" code cell; assert the cell content is absent from the rendered HTML
  - `test_resource_logging` — assert peak-memory log line appears after each notebook
- [ ] **Documentation in script docstring:** owner workflow snippet (`fetch_history.py → export_results.py → git add → commit → push`)

**Acceptance Criteria:**

- `uv run python scripts/export_results.py` (in private mode with `data/` populated) produces all 4 HTML files + 4 JSON files + 4 schema files under `results/static/`
- All emitted JSONs validate against their sibling schemas
- Re-running produces byte-identical JSON except `generated_at`
- Coverage on `scripts/export_results.py` ≥ 90%

---

### Phase 6.4 — Data Boundary Audit (File + API)

**Status:** `[ ]` Pending
**Goal:** Two complementary checks so OHLCV leaks are caught regardless of which frontend (today's FastUI, tomorrow's React, third-party clients) calls the API. The static-file walk catches owner mistakes at commit time; the API-response walk catches runtime regressions in handler code.

**Deliverables:**

- [ ] `tests/integration/test_public_data_boundary_files.py` (NEW):
  - Walks `results/static/**/*.json`; fails if any object key matches `^(open|high|low|close|volume|adj_close|adjusted_close)$` (case-insensitive)
  - Fails if any value array has > 400 numeric entries (heuristic: ~16 years of daily prices ≈ 4000 rows; 400 = 1.5 years which we'd never emit in a "summary")
  - Walks `results/static/**/*.html`; fails if any `<table>` contains > 5 numeric columns (heuristic for raw price tables; rendering charts have 0 numeric columns)
  - Per-file actionable failure messages (e.g. `"results/static/signals/latest_ranking.json: forbidden key 'close' at rankings[3].close"`)
- [ ] `tests/integration/test_public_data_boundary_api.py` (NEW):
  - Boots `TestClient(app)` with `CSM_PUBLIC_MODE=true`
  - Hits `/api/v1/signals/latest`, `/api/v1/backtest/summary`, `/api/v1/backtest/equity_curve`, `/api/v1/portfolio/holdings`, `/api/v1/portfolio/regime`
  - Recursively scans each response JSON for the same forbidden-key set
  - Asserts write endpoints (`/api/v1/data/refresh`, `/api/v1/backtest/run`) return **403** with the canonical "Disabled in public mode" body
- [ ] `.gitignore` extension:
  - Add: `data/raw/`, `data/processed/`, `data/universe/`, `.env`, `.env.*`, `results/.tmp/`
  - Whitelist: `!.env.example`, `!docs/plans/` (preserve plan tracking per project convention)

**Acceptance Criteria:**

- Both audit tests pass on the committed `results/static/` produced by 6.3
- Adding a deliberate OHLCV leak (e.g. an `"close": 1.23` field in `summary.json`) makes the file audit fail with the offending path
- Adding a deliberate leak in an API handler makes the API audit fail
- `git status` shows no unintended files; `data/` is never staged

---

### Phase 6.5 — README Rewrite

**Status:** `[ ]` Pending
**Goal:** Reposition the README around two audiences: (1) the visitor who wants `docker compose up` and a working dashboard, and (2) the developer who sees port 8000 as a Data Engine they can build their own frontend on top of.

**Deliverables:**

- [ ] `README.md` rewrite, in this order:
  - **Badges** — build status (docker-smoke), GHCR pulls, license, Python version
  - **One-liner pitch** — "Cross-Sectional Momentum strategy on the SET. Headless API + pre-computed research; bring your own frontend."
  - **Quick Start (Public)** — `git clone … && cd … && docker compose up` → open `http://localhost:8000`
  - **Pre-built image** — `docker pull ghcr.io/lumduan/csm-set:latest && docker run -p 8000:8000 …` (live after 6.7)
  - **Architecture (Headless)** section — short paragraph + Mermaid diagram (with ASCII fallback) showing port 8000 as the Data Engine API, with three plug-in consumers: today's FastUI, future React/Next.js as a sibling container, and any third-party dashboard. Frames the project as "an API + research artefacts you can build any UI on top of," **not** "a NiceGUI/FastUI app"
  - **What you will see** — notebook gallery, backtest charts, signal rankings (screenshots optional)
  - **What requires credentials** (owner only) — fetching live OHLCV via tvkit, re-running notebooks, generating new signals
  - **Build your own frontend** — short subsection: `results/static/` is a flat asset tree; JSON Schema sidecars feed `npx json-schema-to-typescript`; CORS is preconfigured. Code snippet:
    ```bash
    npx json-schema-to-typescript results/static/backtest/summary.schema.json -o frontend/types/backtest.ts
    fetch('http://localhost:8000/api/v1/signals/latest').then(r => r.json())
    ```
  - **Owner workflow** — `fetch_history.py → export_results.py → git add results/static/ → commit → push`
  - **Development** — `uv sync --all-groups`, quality gate, test commands
  - **Project structure** — short tree
  - **License + acknowledgements**

**Acceptance Criteria:**

- Following the README Quick Start verbatim on a clean machine works (verified by smoke workflow + manual)
- The "Architecture (Headless)" section appears before "What you will see," establishing framing
- A reader unfamiliar with NiceGUI / FastUI understands within the first screen that they can connect their own React app

---

### Phase 6.6 — GitHub Actions CI Smoke Workflow

**Status:** `[ ]` Pending
**Goal:** Make "the public release works" a CI invariant, not a manual sanity check.

**Deliverables:**

- [ ] `.github/workflows/docker-smoke.yml` (NEW):
  - **Triggers:** `pull_request` (any branch → main), `push: branches: [main]`
  - **Concurrency group:** `docker-smoke-${{ github.ref }}` with `cancel-in-progress: true`
  - **Job:** `smoke` on `ubuntu-latest`, timeout 15 min
  - **Steps:**
    1. `actions/checkout@v4`
    2. `docker/setup-buildx-action@v3` with GHA cache backend
    3. `docker compose up -d --wait` (uses `mem_limit: 2g` from compose)
    4. Wait loop: `curl --retry 10 --retry-delay 3 -fsS http://localhost:8000/health`
    5. Assert read endpoints return 200: `/api/v1/signals/latest`, `/api/v1/backtest/summary`, `/static/notebooks/01_data_exploration.html`, `/static/backtest/summary.json`
    6. Assert write endpoints return 403: `curl -o /dev/null -w '%{http_code}' -X POST http://localhost:8000/api/v1/data/refresh` → expects `403`
    7. On failure: `docker compose logs csm > smoke-logs.txt`; upload as artefact
    8. Cleanup: `docker compose down -v`

**Acceptance Criteria:**

- Workflow file passes `actionlint`
- A test PR (introducing a deliberate broken health endpoint) fails the smoke job with the logs artefact
- Wall-clock time on a green run < 5 min

---

### Phase 6.7 — GHCR Image Publishing

**Status:** `[ ]` Pending
**Goal:** Tag-driven release pipeline that publishes versioned, multi-tagged images to GitHub Container Registry, so public users can `docker pull` instead of `docker compose up` (build).

**Deliverables:**

- [ ] `.github/workflows/docker-publish.yml` (NEW):
  - **Triggers:** `push: tags: ['v*.*.*']` and `workflow_dispatch` (manual)
  - **Permissions:** `contents: read`, `packages: write`
  - **Job:** `publish` on `ubuntu-latest`, timeout 30 min
  - **Steps:**
    1. `actions/checkout@v4`
    2. `docker/login-action@v3` with `registry: ghcr.io`, `username: ${{ github.actor }}`, `password: ${{ secrets.GITHUB_TOKEN }}`
    3. `docker/metadata-action@v5` to compute tags: `vX.Y.Z`, `vX.Y`, `latest` (only on highest-versioned tag), `sha-${{ github.sha }}`
    4. `docker/build-push-action@v5` with `platforms: linux/amd64`, `push: true`, `cache-from: type=gha`, `cache-to: type=gha,mode=max`
- [ ] `RELEASING.md` (NEW or appendix in this PLAN) — owner runbook:
  - `git tag -a v0.6.0 -m "Phase 6 release"` → `git push origin v0.6.0`
  - GHCR publish workflow runs automatically
  - Verify: `docker pull ghcr.io/lumduan/csm-set:v0.6.0` from a fresh machine
  - Update README "Pre-built image" section if version-specific

**Acceptance Criteria:**

- Pushing a `v*.*.*` tag triggers the workflow and publishes to `ghcr.io/lumduan/csm-set` with all expected tags
- `docker pull ghcr.io/lumduan/csm-set:latest && docker run -p 8000:8000 ghcr.io/lumduan/csm-set:latest` boots cleanly on a fresh machine
- README badge shows correct latest tag

---

## Data Models

All models are defined in `scripts/_export_models.py` (kept under `scripts/` rather than `src/csm/` because they are distribution-layer concerns, not core strategy logic). Each carries a top-level `schema_version: "1.0"` field; each has a corresponding `<name>.schema.json` sidecar emitted via `Model.model_json_schema()`.

### `BacktestSummary`

```python
class BacktestSummary(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime  # tz-aware Asia/Bangkok
    backtest_period: BacktestPeriod  # {start: date, end: date}
    config: BacktestConfigSnapshot   # canonical config for reproducibility
    metrics: BacktestMetrics         # cagr, sharpe, sortino, calmar, max_drawdown, win_rate, etc.
```

### `EquityCurve`

```python
class EquityPoint(BaseModel):
    date: date
    nav: float            # NAV indexed to 100, NEVER absolute prices
    benchmark_nav: float

class EquityCurve(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    description: str  # explicit reminder: "NAV indexed to 100. No raw price data."
    series: list[EquityPoint]
```

### `AnnualReturns`

```python
class AnnualRow(BaseModel):
    year: int
    portfolio_return: float
    benchmark_return: float

class AnnualReturns(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    rows: list[AnnualRow]
```

### `SignalRanking`

```python
class RankingEntry(BaseModel):
    symbol: str
    sector: str
    quintile: int  # 1..5
    z_score: float
    rank_pct: float  # 0.0..1.0

class SignalRanking(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    as_of: date
    description: str  # "Cross-sectional momentum ranking. No raw price data."
    rankings: list[RankingEntry]
```

### `ExportResultsConfig`

```python
class ExportResultsConfig(BaseModel):
    notebook_dir: Path = Path("notebooks")
    output_dir: Path = Path("results/static")
    execute: bool = True
    timeout_s: int = 600
    memory_budget_mb: int = 2048
    only_notebooks: bool = False
    only_backtest: bool = False
    only_signals: bool = False
```

**Boundary rule:** none of these models contain `open`, `high`, `low`, `close`, `volume`, `adj_close` fields. The boundary audit test enforces this at file *and* API levels.

---

## Error Handling Strategy

| Scenario | Behaviour |
|---|---|
| nbconvert kernel timeout (> 600 s) | Subprocess exits non-zero; export_results logs `notebook_timeout` with offending path; script exits 1 |
| nbconvert OOM (kernel killed) | Subprocess exits 137 / 139; caught by exit-code check; logs `notebook_oom` with hint to raise `--memory` |
| Missing `data/` in private mode | Log warning `data_dir_missing`; skip backtest + signal export; continue with notebooks-only (avoids blocking notebook-only refreshes) |
| Missing `results/static/` in public container | API returns 404 from `/api/v1/signals/latest` (already wired by Phase 5) — handler reads from `results/static/` after path adapter; UI shows "Notebook not yet exported" placeholder |
| HEALTHCHECK fail (e.g. uvicorn crash) | `restart: unless-stopped` triggers container restart; HEALTHCHECK retries 3 before marking unhealthy |
| OHLCV leak detected by file audit | Test fails with `forbidden_key` and full JSON path (`results/static/X.json: rankings[N].close`); CI smoke fails |
| OHLCV leak detected by API audit | Test fails with HTTP path + JSON path (`GET /api/v1/signals/latest → rankings[N].close`); CI smoke fails |
| GHCR push 403 (workflow) | Action exits with `permission_denied`; runbook hint: ensure `permissions: packages: write` block in workflow |
| CORS preflight rejected (browser) | Browser console shows blocked origin; private mode users update `CSM_CORS_ALLOW_ORIGINS` env in `docker-compose.private.yml` |
| `uv sync --frozen` cache miss in builder | Build still succeeds (uv resolves deterministically); slower build, no functional impact |
| `docker compose up` on a host with port 8000 occupied | Compose fails fast with port-bind error; documented in README troubleshooting |
| `tvkit` browser auth missing in private mode | `fetch_history.py` raises `BrowserAuthError`; export_results.py is unaffected (operates on existing parquet) |

---

## Testing Strategy

### Coverage Target

≥ 90% line coverage on `scripts/export_results.py` and `scripts/_export_models.py`. Existing `src/csm/` and `api/` coverage from Phase 5 (92%) must not regress.

### Test File Map

| Concern | Test file |
|---|---|
| CORS preflight + headers | `tests/integration/test_cors.py` |
| File data boundary | `tests/integration/test_public_data_boundary_files.py` |
| API data boundary | `tests/integration/test_public_data_boundary_api.py` |
| Exporter idempotency + schema match | `tests/integration/test_export_results.py` |
| Pydantic models | `tests/unit/scripts/test_export_models.py` |

### Categories

- **Boundary audits (the most important tests in Phase 6)** — file walk + API response walk. Both must be green for any `results/static/` change to merge. These are the production guarantees that prevent the project's defining promise (no raw OHLCV leaks publicly) from regressing.
- **Idempotency tests** — re-running the exporter must produce byte-identical output except `generated_at`. Catches accidental ordering / float-formatting / Pydantic key-shuffling regressions.
- **Schema-data co-validation** — every emitted `<name>.json` must validate against its sibling `<name>.schema.json` (uses the `jsonschema` library). This is the contract test for any future frontend.
- **CORS preflight** — `OPTIONS` returns expected headers; cross-origin `GET` succeeds in public mode and is constrained in private mode.
- **CI smoke (Phase 6.6)** — black-box assertions against a real `docker compose up` boot.

### Quality Gate

```bash
uv run ruff check . && uv run ruff format . && uv run mypy src/ && uv run pytest tests/ -v
```

Must be green for every sub-phase commit. Per project convention, no `--no-verify` skips.

### Manual Sign-off

- Fresh clone in `/tmp/csm-test-fresh/` on macOS and Linux; run `docker compose up`; browser walkthrough of `/`, `/notebooks/01..04`, `/api/docs`
- `docker compose -f docker-compose.yml -f docker-compose.private.yml up` on the owner machine; run `uv run python scripts/export_results.py` inside the container; confirm `results/static/` updates

---

## Success Criteria

| # | Criterion | Measure |
|---|---|---|
| 1 | Cold start works | Fresh clone + `docker compose up` produces `/health` 200 within 30 s |
| 2 | Public exit criteria | All 4 notebook pages render; backtest equity chart renders; signal rankings table renders; zero ERROR-level logs in container |
| 3 | Owner profile works | `docker compose -f docker-compose.yml -f docker-compose.private.yml up` runs `export_results.py` without permission errors |
| 4 | File data boundary intact | `test_public_data_boundary_files.py` passes — no OHLCV in committed JSON; `data/` ignored |
| 5 | API data boundary intact | `test_public_data_boundary_api.py` passes — no OHLCV in any public-mode API response |
| 6 | Image hygiene | `.dockerignore` keeps build context < 50 MB; multi-stage runtime image < 400 MB compressed |
| 7 | Health monitoring | `docker inspect --format='{{.State.Health.Status}}'` reports `healthy` within 60 s |
| 8 | README accuracy | Following README Quick Start verbatim works on a clean macOS or Linux machine |
| 9 | Frontend-agnostic contract | Every `<name>.json` in `results/static/` has a sibling `<name>.schema.json` that it validates against |
| 10 | CORS unblocked | `OPTIONS /api/v1/signals/latest` returns expected `Access-Control-Allow-*` headers; React dev server on `:3000` can fetch in private mode |
| 11 | Quality gates | ruff / format / mypy / pytest all green; coverage ≥ 90% on new `scripts/*.py` modules |
| 12 | Idempotent re-export | `scripts/export_results.py` produces byte-identical JSON on consecutive runs (differs only in `generated_at`) |
| 13 | CI smoke green | `docker-smoke.yml` workflow passes on PR; `/health` + 4 read endpoints + 1 write 403 assertion all pass |
| 14 | GHCR publish works | `v*.*.*` tag triggers `docker-publish.yml`; image appears at `ghcr.io/lumduan/csm-set` with tags `vX.Y.Z`, `vX.Y`, `latest`, `sha-…`; `docker pull` from a fresh machine + `docker run -p 8000:8000` boots cleanly |
| 15 | Conventional commits | Each sub-phase commit follows `feat(scope): …` with emoji header per `agents/git-commit-reviewer.md`; one feature per commit |

---

## Future Enhancements

- **Multi-arch builds** — add `linux/arm64` to `docker-publish.yml` for native Apple Silicon performance (Phase 7 hardening)
- **Image signing** — cosign / Sigstore in the publish workflow; signature verification documented in README (Phase 7)
- **SBOM generation** — `docker buildx build --sbom=true --provenance=true`; attached as a release artefact (Phase 7)
- **Vulnerability scanning** — trivy gate in `docker-smoke.yml`; fail PR on HIGH/CRITICAL CVEs (Phase 7)
- **`docker-compose.dev.yml`** — hot-reload mount of `src/`, `api/`, `ui/` for in-container development without rebuilds
- **Kubernetes / Helm chart** — `deploy/k8s/` manifest, optional readiness/liveness probes mapped to `/health`
- **React/Next.js front-end container** — separate service in `docker-compose.yml`; consumes `/api/v1/*` and `/static/`; demonstrates the headless contract end-to-end
- **Schema evolution policy** — when `BacktestSummary.schema_version` bumps to `2.0`, document the migration in `docs/guides/schema-versioning.md`
- **CDN / static hosting** — publish `results/static/` to GitHub Pages or Cloudflare Pages so non-Docker consumers can fetch artefacts directly

---

## Commit & PR Templates

### Commit Message (Plan — this commit)

```
feat(plan): add master plan for phase 6 docker public distribution

Scopes 7 sub-phases (6.1-6.7) including multi-stage Dockerfile, public +
private compose configs, generic JSON data contract with schema sidecars,
two-layer data boundary audit, README rewrite, CI smoke workflow, and
GHCR publishing. Establishes API-as-Single-Source-of-Truth headless
architecture so the project is portable across FastUI, future React,
and third-party frontends.
```

### Commit Messages (per sub-phase, on implementation)

```
feat(docker): multi-stage Dockerfile + CORS middleware (Phase 6.1)

- Builder stage: uv sync into /opt/venv; runtime stage copies venv only
- HEALTHCHECK on /health; CMD=uvicorn api.main:app on :8000
- .dockerignore excludes data/, tests/, .git/, notebooks/, *.parquet
- api/main.py: CORSMiddleware with env-driven origins (CSM_CORS_ALLOW_ORIGINS)
- tests/integration/test_cors.py: preflight + cross-origin assertions
```

```
feat(docker): public + private docker-compose configs (Phase 6.2)

- docker-compose.yml: port 8000 only, healthcheck, results:ro, mem_limit 2g
- docker-compose.private.yml: writable mounts, tvkit env, chrome auth
- Smoke command documented in compose header
```

```
feat(scripts): export_results.py with JSON Schema sidecars (Phase 6.3)

- export_notebooks/backtest/signals → results/static/
- Pydantic models in scripts/_export_models.py (schema_version: "1.0")
- <name>.schema.json sidecar via Model.model_json_schema() for TS gen
- nbconvert with 600s timeout; resource.getrusage memory logging
- CLI flags: --notebooks-only|--backtest-only|--signals-only|--skip-notebooks
- Idempotent: byte-identical re-runs except generated_at
```

```
feat(tests): two-layer data boundary audit (Phase 6.4)

- test_public_data_boundary_files.py: walks results/static/**, fails on OHLCV
- test_public_data_boundary_api.py: TestClient scans public API responses
- .gitignore: data/{raw,processed,universe}/, .env*, results/.tmp/
```

```
docs(readme): headless architecture + quick start + owner workflow (Phase 6.5)

- Quick Start (docker compose up → localhost:8000)
- Architecture (Headless) section with Mermaid diagram
- Build your own frontend: JSON Schema → TypeScript types
- Owner workflow: fetch_history → export_results → git push
- Pre-built image: docker pull ghcr.io/lumduan/csm-set:latest
```

```
ci(docker): docker-smoke.yml on PR + main (Phase 6.6)

- Triggers: pull_request, push to main; concurrency group cancels stale runs
- compose up --wait; curl /health + read endpoints; assert write 403
- Logs artefact uploaded on failure; teardown with compose down -v
- Wall-clock budget: 5 min on green
```

```
ci(docker): docker-publish.yml on v*.*.* tags (Phase 6.7)

- Triggers: tag push (v*.*.*) + workflow_dispatch
- docker/metadata-action computes vX.Y.Z, vX.Y, latest, sha-… tags
- Pushes to ghcr.io/lumduan/csm-set; linux/amd64 only (arm64 deferred)
- RELEASING.md: owner runbook for cutting a release
```

### PR Description Template

```markdown
## Summary

Phase 6 — Docker & Public Distribution. Wraps the validated Phase 5 API/UI
in a production-grade multi-stage Docker image, ships a frontend-agnostic
JSON data contract with JSON Schema sidecars, and adds CI smoke-testing +
GHCR image publishing. The defining architectural shift: port 8000 is the
project's Data Engine API, FastUI is one consumer of it, and the project
is no longer tied to any single frontend.

- Multi-stage Dockerfile (builder + slim runtime); HEALTHCHECK on /health
- CORS middleware; env-driven origins (unblocks future React/Next.js)
- docker-compose.yml (public, port 8000) + docker-compose.private.yml (owner)
- scripts/export_results.py: notebooks → HTML, backtest+signals → JSON + .schema.json
- Two-layer data boundary audit (file walk + API response scan)
- README rewrite: Quick Start, Architecture (Headless), Build your own frontend
- .github/workflows/docker-smoke.yml: PR-gated docker compose smoke test
- .github/workflows/docker-publish.yml: tag-driven GHCR publish (vX.Y.Z, vX.Y, latest, sha-…)

## Test plan

- [ ] `uv run pytest tests/integration/test_cors.py -v`
- [ ] `uv run pytest tests/integration/test_public_data_boundary_files.py -v`
- [ ] `uv run pytest tests/integration/test_public_data_boundary_api.py -v`
- [ ] `uv run pytest tests/integration/test_export_results.py -v`
- [ ] `uv run mypy src/ scripts/`
- [ ] `uv run ruff check . && uv run ruff format .`
- [ ] Manual: `docker compose up` from a fresh clone → `localhost:8000` shows notebooks + backtest + rankings
- [ ] Manual: `docker compose -f docker-compose.yml -f docker-compose.private.yml up`; run export_results.py inside; verify results/static/ updates
- [ ] Manual: `OPTIONS http://localhost:8000/api/v1/signals/latest` returns expected CORS headers
- [ ] CI: `docker-smoke.yml` green on this PR
- [ ] Post-merge: tag `v0.6.0`, confirm `docker-publish.yml` pushes to GHCR, `docker pull ghcr.io/lumduan/csm-set:v0.6.0` boots cleanly
```
