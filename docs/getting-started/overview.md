# Getting Started

Get csm-set running on your machine in under 5 minutes. This guide covers both the public Docker quickstart (no credentials needed) and the local development setup with `uv`.

## Docker quickstart (public mode)

No credentials, no configuration. Just Docker.

```bash
git clone https://github.com/lumduan/csm-set
cd csm-set
docker compose up
```

Open [http://localhost:8000](http://localhost:8000). The container boots uvicorn in public mode, serves pre-computed research artefacts (notebook HTML, backtest metrics, signal rankings), and exposes the full REST API.

### Pre-built image

Skip the build step:

```bash
docker pull ghcr.io/lumduan/csm-set:latest
docker run -p 8000:8000 ghcr.io/lumduan/csm-set:latest
```

The image is multi-platform (`linux/amd64`) and built on every versioned tag push.

---

## Local uv quickstart

For development or private-mode use (requires Python 3.11+ and [uv](https://docs.astral.sh/uv/)):

```bash
git clone https://github.com/lumduan/csm-set
cd csm-set

# Install all dependencies
uv sync --all-groups

# Optional: copy the env template for private mode
cp .env.example .env

# Run the API server
uv run uvicorn api.main:app --reload --port 8000

# In another terminal, run the UI (optional)
uv run python ui/main.py
```

Open [http://localhost:8000](http://localhost:8000) for the API + dashboard, or [http://localhost:8000/api/docs](http://localhost:8000/api/docs) for the interactive OpenAPI schema.

---

## First contact — what to look at

Once the server is running, start with these endpoints:

| URL | What it shows |
|-----|---------------|
| `/health` | Health check — confirms the server is alive |
| `/api/docs` | Interactive OpenAPI (Swagger) — explore every endpoint |
| `/api/v1/signals/latest` | Latest cross-sectional momentum ranking (JSON) |
| `/api/v1/backtest/summary` | Backtest performance metrics (CAGR, Sharpe, max DD) |
| `/static/notebooks/01_data_exploration.html` | Data quality audit notebook (HTML) |
| `/` | FastUI dashboard — navigation to all views |

---

## Running tests

The project ships with 827 tests across 61 test files. Run the full suite:

```bash
uv run pytest tests/ -v
```

Run with coverage (enforced at 90% on `api/`):

```bash
uv run pytest tests/ -v --cov=api --cov-fail-under=90
```

For the full quality gate (lint, format, type-check, test):

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src/ && uv run pytest tests/ -v
```

See [docs/development/overview.md](../development/overview.md) for the complete development workflow.

---

## Next steps

- [Architecture Overview](../architecture/overview.md) — understand the monorepo layers and data flow
- [Docker Guide](../guides/docker.md) — private mode, CORS config, troubleshooting
- [Public Mode Guide](../guides/public-mode.md) — data boundary rules, owner workflow
- [Momentum Concept](../concepts/momentum.md) — Jegadeesh–Titman theory and SET implementation
- [Module Reference](../reference/) — per-subpackage API surface
