# Stack Decisions — csm-set

Why each tool was chosen. One-liner per decision; rationale captures the trade-off.

## Package & Runtime

- **uv** — fastest resolver, deterministic locks, single binary. Replaces pip / poetry / conda. Trade-off: newer than poetry, smaller community knowledge base.
- **Python 3.11+** — required for typing improvements (`Self`, better generics) and asyncio performance gains. Trade-off: forecloses use on older infra.

## Web / API

- **FastAPI** — async-native, OpenAPI for free, Pydantic-native, mature. Trade-off: opinionated about Pydantic versions; we accept that as a feature.
- **uvicorn** — lightweight ASGI server, official FastAPI pairing.

## UI

- **NiceGUI** — Python-only UI for a quant-research team without a frontend dev. Trade-off: less polished than a real frontend stack; acceptable for internal tools.

## Data

- **pandas + PyArrow / Parquet** — columnar storage for time-series, zero-copy interop, fast partitioned reads. Trade-off: pandas memory model; we mitigate with column pruning and partitioned reads.
- **numpy / scipy** — established numeric foundation under pandas.

## Domain Data

- **settfex** — canonical SET (Stock Exchange of Thailand) symbol source. Replaces legacy `thai-securities-data`. **Do not reintroduce the legacy package.**
- **tvkit** — TradingView data fetching for cross-checks and missing series.

## Validation / Config

- **pydantic v2** — speed + ergonomics for data validation; standard across FastAPI and our internal models.
- **pydantic-settings** — env-driven config; no hidden globals.

## HTTP

- **httpx** — async HTTP everywhere. **`requests` is forbidden** in `src/csm/` (sync, blocks the event loop).

## Scheduling

- **APScheduler** — embedded scheduling without a separate worker process. Trade-off: not horizontally scalable; fine for a single-host research stack. Lives in `scripts/`, never inside `api/`.

## Quality Tooling

- **pytest + pytest-asyncio** — standard, mature, async-native.
- **mypy** — strict type checking on `src/csm/`.
- **ruff** — single tool replaces flake8 + isort + black for our needs; fast.
- **pre-commit** — local quality gate before commit.

## Notebooks

- **JupyterLab + nbconvert** — research workflow.
- Convention: notebook **markdown cells in Thai**; code stays English.

## What We Deliberately Don't Use

- `requests` — sync; replaced by `httpx`.
- `poetry` / `pip-tools` — replaced by `uv`.
- `conda` / `mamba` — replaced by `uv`.
- SQLite / Postgres in core — Parquet covers durable storage; revisit if `api/` ever needs persistent app state.
- `thai-securities-data` (legacy) — replaced by `settfex`.
