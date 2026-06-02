# Getting Started

This page gets you from zero to a running csm-set instance in under 5 minutes, using either Docker (recommended for first-time users) or a local uv development environment.

## Table of Contents

- [Docker quickstart (public)](#docker-quickstart-public)
- [Pre-built image from GHCR](#pre-built-image-from-ghcr)
- [Local uv quickstart](#local-uv-quickstart)
- [First contact](#first-contact)
- [Running tests](#running-tests)
- [Next steps](#next-steps)

---

## Docker quickstart (public)

No credentials needed. Just Docker.

```bash
git clone https://github.com/lumduan/csm-set
cd csm-set
docker compose up
```

Open [http://localhost:8100](http://localhost:8100).

The container boots uvicorn in public mode (read-only), serves pre-computed research artefacts (notebook HTML, backtest metrics, signal rankings), and exposes the full REST API. Nothing to configure.

Stop with `Ctrl+C` or `docker compose down`.

### What happens at boot

1. Docker builds the image from the multi-stage `Dockerfile` (builder + slim runtime).
2. The container starts uvicorn on port 8000 with `CSM_PUBLIC_MODE=true` (mapped to host port 8100).
3. A healthcheck runs `curl -f http://localhost:8000/health` every 30 seconds (inside container).
4. `results/static/` is mounted read-only into the container.
5. The FastUI dashboard is served at `/`; API docs at `/api/docs`.

---

## Pre-built image from GHCR

Skip the build step entirely:

```bash
docker pull ghcr.io/lumduan/csm-set:latest
docker run -p 8100:8000 ghcr.io/lumduan/csm-set:latest
```

Available tags: `latest`, `vX.Y.Z`, `vX.Y`, `sha-<short-sha>`. See [RELEASING.md](../../RELEASING.md) for the release process.

---

## Local uv quickstart

For development or private-mode use with live data fetching.

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- [tvkit](https://github.com/lumduan/tvkit) credentials (for private mode only)

### Setup

```bash
git clone https://github.com/lumduan/csm-set
cd csm-set
uv sync --all-groups

# Create your local config
cp .env.example .env
# Edit .env if using private mode:
#   CSM_PUBLIC_MODE=false
#   CSM_API_KEY=<generate with python -c 'import secrets; print(secrets.token_urlsafe(32))'>
#   Add tvkit credentials as needed
```

### Run the API

```bash
uv run uvicorn api.main:app --reload --port 8000
```

### Run the UI (if using standalone NiceGUI)

```bash
uv run python ui/main.py
```

In public mode (`CSM_PUBLIC_MODE=true`, the default for the Docker image), the API serves read-only data and the embedded FastUI dashboard. In private mode, all write endpoints are enabled and protected by `X-API-Key`.

---

## First contact

Once the server is running on `http://localhost:8100`, try these in order:

| Endpoint | What you'll see |
|----------|----------------|
| [`/health`](http://localhost:8100/health) | Service status, version, public-mode flag, scheduler state, pending job count |
| [`/api/docs`](http://localhost:8100/api/docs) | Interactive OpenAPI (Swagger) — explore every endpoint |
| [`/api/v1/signals/latest`](http://localhost:8100/api/v1/signals/latest) | Latest cross-sectional momentum rankings (JSON) |
| [`/api/v1/backtest/summary`](http://localhost:8100/api/v1/backtest/summary) | Backtest metrics — CAGR, Sharpe, Sortino, max DD |
| [`/static/notebooks/01_data_exploration.html`](http://localhost:8100/static/notebooks/01_data_exploration.html) | Data quality audit notebook |
| [`/`](http://localhost:8100) | FastUI dashboard with navigation to all notebooks |

---

## Running tests

```bash
# Full quality gate (same commands that CI runs):
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run pytest tests/ -v --cov=api --cov-fail-under=90
```

The coverage floor is 90% on `api/`, enforced in `pyproject.toml`. The full suite includes ~820 tests across unit and integration layers.

See [docs/development/overview.md](../development/overview.md) for the full development workflow and quality gate documentation.

---

## Next steps

- [Architecture Overview](../architecture/overview.md) — understand the layer structure and data flow
- [Docker Guide](../guides/docker.md) — public vs. private compose, healthcheck, CORS
- [Public Mode Guide](../guides/public-mode.md) — data boundary rules, owner workflow
- [Momentum Concept](../concepts/momentum.md) — theoretical background of the strategy
- [Module Reference](../reference/) — per-subpackage API surface for extending the codebase
