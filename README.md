# csm-set

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![uv](https://img.shields.io/badge/managed%20by-uv-purple)](https://docs.astral.sh/uv/)
[![Type Safety](https://img.shields.io/badge/type%20safety-mypy%20strict-green)](pyproject.toml)
[![Docker](https://img.shields.io/badge/docker-ready-blue)](Dockerfile)
[![CI Smoke](https://github.com/lumduan/csm-set/actions/workflows/docker-smoke.yml/badge.svg)](https://github.com/lumduan/csm-set/actions/workflows/docker-smoke.yml)
[![GHCR](https://img.shields.io/badge/GHCR-coming%20in%206.7-lightgrey)](https://github.com/lumduan/csm-set/pkgs/container/csm-set)

โครงการนี้ใช้กลยุทธ์ Cross-Sectional Momentum บนตลาดหุ้นไทย (SET)
โดยดึงข้อมูลผ่าน [tvkit](https://github.com/lumduan/tvkit) แล้วก็คำนวณ momentum signal → rank หุ้น → backtest → แสดงผลใน dashboard

**Cross-Sectional Momentum strategy for the Stock Exchange of Thailand.**
Headless API + pre-computed research — bring your own frontend.
Powered by [tvkit](https://github.com/lumduan/tvkit), pandas/numpy, and FastAPI.

---

> **⚠️ Disclaimer**
>
> โปรเจกต์นี้จัดทำขึ้นเพื่อการศึกษาเท่านั้น ไม่ถือเป็นคำแนะนำการลงทุนในทุกกรณี
> ผลการทดสอบย้อนหลัง (backtest) ไม่ได้รับประกันผลตอบแทนในอนาคต
> ผู้พัฒนาไม่รับผิดชอบต่อความเสียหายหรือผลกำไรขาดทุนใดๆ ที่เกิดจากการนำโปรเจกต์นี้ไปใช้งาน
>
> **This project is for educational purposes only. It does not constitute investment advice.**
> **Past backtest results do not guarantee future returns.**
> **The developer assumes no responsibility for any losses or damages arising from use of this project.**

---

## Development Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Data Pipeline | `[x]` Completed |
| 2 | Signal Research | `[x]` Completed |
| 3 | Backtesting | `[x]` Completed |
| 4 | Portfolio & Risk | `[x]` Completed |
| 5 | API + FastUI | `[x]` Completed |
| **6** | **Docker & Public Distribution** | **`[~]` In progress** |
| 7 | CI/CD & Hardening | `[ ]` Pending |
| 8 | Documentation & Polish | `[ ]` Pending |

**Phase 6 sub-progress:** Multi-stage Dockerfile (6.1 ✓), Docker Compose dual config (6.2 ✓), Export results script with JSON Schema sidecars (6.3 ✓), Data boundary audit — file + API (6.4 ✓), README rewrite (6.5 ✓), CI smoke workflow (6.6 ✓), GHCR image publishing (6.7 — pending).

See the full roadmap at [docs/plans/ROADMAP.md](docs/plans/ROADMAP.md).

---

## What this project does

- Computes cross-sectional momentum signals (Jegadeesh–Titman: 12-1M, 6-1M, 3-1M)
- Walk-forward backtest with realistic transaction costs
- Market regime detection via 200-day SMA of the SET index
- Three portfolio construction modes — equal weight, volatility-target, minimum-variance
- FastAPI Data Engine on port 8000 + embedded FastUI dashboard
- Frontend-agnostic JSON data contract with JSON Schema sidecars

---

## Quick Start (Public)

No credentials needed. Just Docker.

```bash
git clone https://github.com/lumduan/csm-set
cd csm-set
docker compose up
```

Open [http://localhost:8000](http://localhost:8000).

The container boots uvicorn in public mode, serves pre-computed research artefacts (notebook HTML, backtest metrics, signal rankings), and exposes the full REST API. Nothing to configure — it just works.

### Pre-built image (coming in Phase 6.7)

Once GHCR publishing is live, you will be able to skip the build step:

```bash
docker pull ghcr.io/lumduan/csm-set:latest
docker run -p 8000:8000 ghcr.io/lumduan/csm-set:latest
```

---

## Architecture (Headless)

CSM-SET is designed as a **Data Engine** on port 8000, not a monolithic dashboard app.

FastUI is one consumer of the API today, but the API and static asset tree are framework-agnostic. Any frontend — React, Next.js, Vue, Flutter, or a third-party dashboard — can consume the same endpoints and JSON artefacts without backend changes.

```
                     ┌──────────────────────────┐
                     │  CSM-SET Container       │
                     │  port 8000  uvicorn      │
                     │  ┌────────────────────┐  │
                     │  │  FastAPI app       │  │
                     │  │   /api/v1/...      │  │◄──── React / Next.js (future)
                     │  │   /static/...      │  │◄──── Mobile app (future)
                     │  │   /                 │  │◄──── Third-party dashboard
                     │  │   (FastUI mount)   │  │◄──── FastUI (today, embedded)
                     │  └────────────────────┘  │
                     │  results/static/         │
                     │   ├── notebooks/         │
                     │   ├── backtest/          │
                     │   └── signals/           │
                     └──────────────────────────┘
```

```mermaid
graph TB
    subgraph Container["CSM-SET Container (port 8000)"]
        API["FastAPI app<br/>/api/v1/... | /static/..."]
        RESULTS["results/static/<br/>notebooks/ | backtest/ | signals/"]
        FU["FastUI mount at /"]
    end
    REACT["React / Next.js (future)"] --> API
    MOBILE["Mobile app (future)"] --> API
    THIRD["Third-party dashboard"] --> API
    FU --> API
    RESULTS --> API
```

Port 8000 serves:

- **REST endpoints** under `/api/v1/` — signals, backtest results, portfolio state, notebook listings, health
- **Static artefacts** under `/static/` — notebook HTML, backtest JSON, signal JSON
- **Embedded FastUI dashboard** at `/` — a full working UI with zero extra build steps

Write endpoints (`/api/v1/data/refresh`, `/api/v1/backtest/run`, `/api/v1/scheduler/run/*`, `/api/v1/jobs`) return `403` in public mode with a canonical "Disabled in public mode" response.

---

## What you will see

At `http://localhost:8000`:

| Page | Content |
|------|---------|
| `/` | FastUI dashboard — navigation to notebooks, backtest, signals |
| `/notebooks/01_data_exploration` | Data quality audit: coverage, gaps, distributions |
| `/notebooks/02_signal_research` | Momentum signal analysis: IC, quintile spreads, decay |
| `/notebooks/03_backtest_analysis` | Walk-forward backtest: equity curve, drawdown, turnover |
| `/notebooks/04_portfolio_optimization` | Portfolio construction: weight schemes, regime overlay |
| `/api/v1/signals/latest` | Latest cross-sectional ranking (JSON) |
| `/api/v1/backtest/summary` | Backtest metrics: CAGR, Sharpe, Sortino, max DD |
| `/api/docs` | OpenAPI (Swagger) — explore every endpoint interactively |

---

## What requires credentials (owner only)

Everything visible in public mode works with zero configuration. The following operations require a [tvkit](https://github.com/lumduan/tvkit) setup with TradingView credentials:

| Operation | Requires | Script |
|-----------|----------|--------|
| Fetch live OHLCV data | tvkit + Chrome profile | `scripts/fetch_history.py` |
| Build universe snapshots | fetched data | `scripts/build_universe.py` |
| Re-run notebooks | fetched data | `scripts/export_results.py --notebooks-only` |
| Generate new backtest results | fetched data + signal pipeline | `scripts/export_results.py --backtest-only` |
| Generate new signal rankings | fetched data + feature pipeline | `scripts/export_results.py --signals-only` |

---

## Build your own frontend

`results/static/` is a flat, frontend-agnostic asset tree:

```
results/static/
├── notebooks/                    # nbconvert HTML (no code cells)
├── backtest/
│   ├── summary.json              # CAGR, Sharpe, Sortino, max DD, win rate
│   ├── summary.schema.json       # JSON Schema draft-2020-12
│   ├── equity_curve.json         # NAV indexed to 100 (no raw prices)
│   ├── equity_curve.schema.json
│   ├── annual_returns.json
│   └── annual_returns.schema.json
└── signals/
    ├── latest_ranking.json       # Symbol, sector, quintile, z-score, rank %
    └── latest_ranking.schema.json
```

Every `<name>.json` carries `"schema_version": "1.0"` and a sibling `<name>.schema.json`. Generate TypeScript types in one command:

```bash
npx json-schema-to-typescript results/static/backtest/summary.schema.json \
  -o frontend/types/backtest.ts
```

Then fetch live data from the API:

```javascript
const rankings = await fetch('http://localhost:8000/api/v1/signals/latest')
  .then(r => r.json());
// rankings.rankings: Array<{ symbol, sector, quintile, z_score, rank_pct }>
```

**CORS is preconfigured.** In public mode, `CSM_CORS_ALLOW_ORIGINS` defaults to `*`. In private mode, restrict it to your dev server (e.g., `http://localhost:3000,http://localhost:5173`) via the `docker-compose.private.yml` override.

No raw OHLCV fields (`open`, `high`, `low`, `close`, `volume`, `adj_close`) appear in any JSON artefact or API response. This is enforced by automated boundary audit tests.

---

## Owner workflow

If you have tvkit credentials and want to refresh the public research:

```bash
cp .env.example .env
# Set CSM_PUBLIC_MODE=false and add your tvkit credentials
```

### Via Docker (recommended)

```bash
docker compose -f docker-compose.yml -f docker-compose.private.yml up -d
docker compose exec csm bash

# Inside the container:
uv run python scripts/fetch_history.py      # Pull OHLCV via tvkit
uv run python scripts/build_universe.py     # Build monthly snapshots
uv run python scripts/export_results.py     # Notebooks → HTML, backtest + signals → JSON
exit

# Back on the host:
git add results/static/
git commit -m "results: refresh $(date +%Y-%m-%d)"
git push
```

### Via local uv

```bash
uv sync --all-groups

uv run python scripts/fetch_history.py
uv run python scripts/build_universe.py
uv run python scripts/export_results.py

git add results/static/
git commit -m "results: refresh $(date +%Y-%m-%d)"
git push
```

Public users get the updated research on their next `git pull` or image rebuild.

---

## Stack

| Concern | Technology |
|---------|------------|
| Data ingestion | tvkit, pyarrow, pandas |
| Research | numpy, scipy, scikit-learn |
| API | FastAPI, uvicorn, APScheduler |
| UI | NiceGUI (FastUI, mounted on FastAPI) |
| Config | pydantic-settings |
| Tooling | uv, ruff, mypy, pytest |

---

## Development

```bash
uv sync --all-groups
cp .env.example .env

# Quality gate — run before every commit:
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run pytest tests/ -v

# Run API + UI locally:
uv run uvicorn api.main:app --reload --port 8000
uv run python ui/main.py
```

---

## Project structure

```
csm-set/
├── api/                          # FastAPI app, routers, middleware, schemas
├── src/csm/                      # Core library: config, data, signals, portfolio, backtest, risk
├── ui/                           # FastUI views (mounted on the FastAPI app)
├── scripts/                      # Owner utilities: fetch_history, export_results, build_universe
├── notebooks/                    # Jupyter research notebooks (Thai markdown, English code)
├── tests/                        # Test suite (unit + integration)
├── results/                      # Pre-computed research artefacts (committed)
│   └── static/                   # Frontend-agnostic JSON + HTML + Schema sidecars
├── data/                         # Raw/processed Parquet files (gitignored)
├── docs/                         # Documentation and plans
├── Dockerfile                    # Multi-stage: builder + slim runtime
├── docker-compose.yml            # Public: port 8000, results:ro, healthcheck, mem_limit 2g
├── docker-compose.private.yml    # Owner override: writable mounts, tvkit auth
└── pyproject.toml                # Project metadata, dependencies, tool config
```

---

## Documentation

- [Getting Started](docs/getting-started/overview.md)
- [Architecture Overview](docs/architecture/overview.md)
- [Docker Guide](docs/guides/docker.md)
- [Public Mode Guide](docs/guides/public-mode.md)
- [Momentum Concept](docs/concepts/momentum.md)
- [Development Guide](docs/development/overview.md)
- [Reference: Data Layer](docs/reference/data/overview.md)
- [Reference: Features](docs/reference/features/overview.md)
- [Reference: Portfolio](docs/reference/portfolio/overview.md)
- [Reference: Research](docs/reference/research/overview.md)
- [Reference: Risk](docs/reference/risk/overview.md)
- [API Reference (OpenAPI)](http://localhost:8000/api/docs) — available when the container is running
- [Master Roadmap](docs/plans/ROADMAP.md)

---

## References

- Jegadeesh & Titman (1993). *Returns to Buying Winners and Selling Losers*
- Asness, Moskowitz & Pedersen (2013). *Value and Momentum Everywhere*
- Rouwenhorst (1999). *Local Return Factors in Emerging Stock Markets*

---

## License

MIT — see [LICENSE](LICENSE)
