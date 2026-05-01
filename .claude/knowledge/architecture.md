# Architecture — csm-set

Cross-Sectional Momentum strategy system for the Stock Exchange of Thailand (SET). Python 3.11+, async-first, Pydantic-typed, uv-managed.

## Top-Level Layout

| Path | Purpose |
|---|---|
| `src/csm/` | Core library — signals, portfolios, backtests, reporting. Importable. |
| `api/` | FastAPI service exposing csm functionality over HTTP. |
| `ui/` | NiceGUI dashboard for research / monitoring. |
| `scripts/` | Operational scripts (data fetch, builds, exports, publish). |
| `notebooks/` | Jupyter research notebooks (markdown in Thai). |
| `tests/` | pytest suite mirroring `src/csm/` structure. |
| `data/` | Raw / intermediate Parquet (gitignored). |
| `results/` | Computed outputs (selectively tracked — see `.gitignore`). |
| `docs/` | Design docs, plans (`docs/plans/` is **always** git-tracked). |
| `examples/` | Runnable usage examples (`uv run python examples/<name>.py`). |
| `.claude/` | Agent / knowledge / memory / playbook config. |

## Module Boundaries (data flow)

```
settfex / tvkit  →  src/csm/data       (fetch, normalize, persist Parquet)
                 →  src/csm/signals    (momentum, ranking)
                 →  src/csm/portfolio  (construction, weights, constraints)
                 →  src/csm/backtest   (simulation, P&L, metrics)
                 →  src/csm/report     (artifacts in results/)
                 ↗
       api/ (FastAPI)  ←  exposes read endpoints over backtests / signals
       ui/  (NiceGUI)  ←  research dashboard, calls api/ or src/ directly
```

Direction is one-way: lower layers must not import from higher ones. `api/` and `ui/` may import `src/csm/`; `src/csm/` must not import from `api/` or `ui/`.

## Storage

- **Parquet via PyArrow** for all tabular, durable data (price history, signals, portfolios).
- **Partition by date** for time-series Parquet datasets where feasible.
- **No SQLite / Postgres** in core — only Parquet. (`api/` may add a thin metadata DB if and when needed; route through `pydantic-settings`.)

## Scheduling

- **APScheduler** lives in `scripts/` (e.g., daily fetch, end-of-day report).
- **Never** embed schedulers in `api/` (the API is a stateless service).

## Configuration

- All runtime config via `pydantic-settings` reading from env (or `.env` for local dev).
- No hard-coded paths — base paths come from a single `Settings` object in `src/csm/config.py`.
- Time zone: `Asia/Bangkok`, set via settings, applied at every IO boundary.

## Cross-Cutting Conventions

- All I/O is async at boundaries; sync internal compute (pandas/numpy) is fine.
- Errors: module-specific exceptions defined in each subpackage's `errors.py`, inheriting from a single `CsmError`.
- Logging: `logging.getLogger(__name__)`; no `print` in `src/csm/`.
