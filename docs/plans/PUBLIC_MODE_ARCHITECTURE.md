# CSM-SET: Public Mode — Architecture & Implementation Guide

Open-source distribution design for the CSM-SET project.
Anyone can clone and run via Docker. Raw market data never enters the repository.

---

## Core Principle

```
Repo contains:      code + pre-computed results
Repo never has:     raw prices, adjusted prices, tvkit credentials, symbol OHLCV data
```

Public users see the research output. Only the owner (with tvkit credentials) can regenerate it.

---

## Two Runtime Modes

| | Private (owner) | Public (anyone) |
|---|---|---|
| `CSM_PUBLIC_MODE` | `false` | `true` |
| Fetch live data | yes | no — `DataAccessError` |
| Re-run notebooks | yes | no |
| Refresh signals | yes | no — 403 |
| Run new backtest | yes | no — 403 |
| View notebook HTML | yes | yes |
| View backtest results | yes | yes |
| View signal ranking | yes | yes |

---

## Additional Files vs Original Structure

```
csm-set/
│
├── results/                              # committed to git — pre-computed outputs only
│   ├── notebooks/
│   │   ├── 01_data_exploration.html      # jupyter nbconvert --to html (no kernel)
│   │   ├── 02_signal_research.html
│   │   ├── 03_backtest_analysis.html
│   │   └── 04_portfolio_optimization.html
│   ├── backtest/
│   │   ├── summary.json                  # CAGR, Sharpe, Sortino, max DD, win rate
│   │   ├── equity_curve.json             # monthly NAV indexed to 100 (no raw prices)
│   │   └── annual_returns.json           # year-by-year return table
│   └── signals/
│       └── latest_ranking.json           # symbol, quintile, z_score, sector (no OHLCV)
│
├── Dockerfile                            # single image: api + ui
├── docker-compose.yml                    # one-command startup
├── docker-compose.private.yml            # override for owner: mounts data/, enables refresh
│
├── src/csm/
│   └── config/
│       └── settings.py                   # ADD: public_mode: bool field
│
├── api/
│   ├── main.py                           # ADD: public_mode middleware
│   └── routers/
│       ├── data.py                       # ADD: 403 guard when public_mode=true
│       ├── backtest.py                   # ADD: 403 guard when public_mode=true
│       ├── signals.py                    # ADD: reads results/signals/ when public_mode=true
│       └── portfolio.py                  # ADD: reads results/backtest/ when public_mode=true
│
├── ui/
│   └── pages/
│       ├── dashboard.py                  # ADD: hide "Refresh Data" button in public mode
│       ├── backtest.py                   # ADD: show pre-computed results only in public mode
│       └── notebooks.py                  # NEW PAGE: serve static HTML notebooks via iframe
│
└── scripts/
    └── export_results.py                 # NEW: run notebooks → HTML + export JSON to results/
```

---

## New & Modified Files — Full Specification

---

### `results/` — Committed Pre-computed Outputs

**`results/backtest/summary.json`** — schema:
```json
{
  "generated_at": "2025-01-01",
  "backtest_period": { "start": "2005-01-01", "end": "2024-12-31" },
  "config": {
    "formation_months": 12,
    "skip_months": 1,
    "top_quantile": 0.2,
    "weight_scheme": "equal",
    "rebalance_frequency": "monthly"
  },
  "metrics": {
    "cagr": 0.142,
    "sharpe": 0.81,
    "sortino": 1.12,
    "calmar": 0.63,
    "max_drawdown": -0.312,
    "win_rate": 0.587,
    "avg_monthly_return": 0.011,
    "annualised_volatility": 0.173,
    "alpha_vs_set": 0.064,
    "beta_vs_set": 0.74
  }
}
```

**`results/backtest/equity_curve.json`** — monthly NAV indexed to 100, no absolute prices:
```json
{
  "description": "Portfolio NAV indexed to 100 at start. No raw price data.",
  "series": [
    { "date": "2005-01-31", "nav": 100.0, "benchmark_nav": 100.0 },
    { "date": "2005-02-28", "nav": 101.3, "benchmark_nav": 100.8 }
  ]
}
```

**`results/signals/latest_ranking.json`** — no OHLCV, only derived scores:
```json
{
  "as_of": "2025-01-31",
  "description": "Cross-sectional momentum ranking. No raw price data.",
  "rankings": [
    { "symbol": "AOT", "sector": "SERVICE", "quintile": 5, "z_score": 1.82, "rank_pct": 0.94 },
    { "symbol": "CPALL", "sector": "CONSUMP", "quintile": 5, "z_score": 1.61, "rank_pct": 0.91 }
  ]
}
```

---

### `src/csm/config/settings.py` — Add public_mode field

```python
class Settings(BaseSettings):
    # ... existing fields ...

    public_mode: bool = False
    """
    When True:
    - All data fetch operations raise DataAccessError
    - API write/refresh endpoints return 403
    - UI hides data management controls
    - Signal and portfolio endpoints read from results/ directory
    """

    results_dir: Path = Path("./results")
    """Directory containing pre-computed outputs committed to git."""
```

---

### `src/csm/data/loader.py` — Guard in public mode

```python
class OHLCVLoader:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def fetch(self, symbol: str, interval: str, bars: int) -> pd.DataFrame:
        if self._settings.public_mode:
            raise DataAccessError(
                "Data fetching is disabled in public mode. "
                "Raw market data is not distributed with this repository. "
                "Set CSM_PUBLIC_MODE=false and provide tvkit credentials to enable."
            )
        # ... existing fetch logic ...
```

---

### `api/main.py` — Public mode middleware

```python
from fastapi import Request, Response

WRITE_ENDPOINTS = {
    "/api/v1/data/refresh",
    "/api/v1/backtest/run",
}

@app.middleware("http")
async def public_mode_guard(request: Request, call_next: Callable) -> Response:
    if settings.public_mode and request.url.path in WRITE_ENDPOINTS:
        return Response(
            content='{"detail": "Disabled in public mode. Run with CSM_PUBLIC_MODE=false to enable."}',
            status_code=403,
            media_type="application/json",
        )
    return await call_next(request)
```

---

### `api/routers/signals.py` — Fallback to results/ in public mode

```python
@router.get("/signals/latest")
async def get_latest_signals(
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[ParquetStore, Depends(get_store)],
) -> dict:
    if settings.public_mode:
        # Read pre-computed JSON from results/
        results_path = settings.results_dir / "signals" / "latest_ranking.json"
        if not results_path.exists():
            raise HTTPException(status_code=404, detail="No pre-computed signals found.")
        return json.loads(results_path.read_text())
    # ... existing live logic ...
```

Apply same pattern to `api/routers/portfolio.py` and `api/routers/backtest.py`.

---

### `ui/pages/notebooks.py` — NEW: static HTML notebook viewer

```python
"""Serve pre-computed notebook HTML exports via NiceGUI iframe."""

from pathlib import Path
from nicegui import ui
from csm.config.settings import settings

NOTEBOOK_PAGES = [
    ("01 — Data Exploration",       "01_data_exploration.html"),
    ("02 — Signal Research",        "02_signal_research.html"),
    ("03 — Backtest Analysis",      "03_backtest_analysis.html"),
    ("04 — Portfolio Optimization", "04_portfolio_optimization.html"),
]

def notebook_page() -> None:
    """NiceGUI page: tabbed static HTML notebook viewer."""
    with ui.tabs().classes("w-full") as tabs:
        tab_objects = [ui.tab(label) for label, _ in NOTEBOOK_PAGES]

    with ui.tab_panels(tabs, value=tab_objects[0]).classes("w-full"):
        for (label, filename), tab in zip(NOTEBOOK_PAGES, tab_objects):
            html_path = settings.results_dir / "notebooks" / filename
            with ui.tab_panel(tab):
                if html_path.exists():
                    # Serve HTML as static file, display in iframe
                    ui.html(f'<iframe src="/static/notebooks/{filename}" '
                            f'style="width:100%; height:85vh; border:none;"></iframe>')
                else:
                    ui.label(f"Notebook not yet exported: {filename}").classes("text-warning")
                    ui.label("Run: uv run python scripts/export_results.py")
```

Register `/static/notebooks/` as a FastAPI StaticFiles mount pointing to `results/notebooks/`.

---

### `ui/pages/dashboard.py` — Hide controls in public mode

```python
def dashboard_page() -> None:
    # ... existing portfolio snapshot, regime badge ...

    if not settings.public_mode:
        # Only show to owner
        with ui.card():
            ui.label("Data Management").classes("text-subtitle")
            ui.button("Refresh Data", on_click=trigger_refresh).classes("bg-primary")
            ui.label(f"Last refresh: {last_refresh_time()}")
    else:
        ui.label("Read-only mode — pre-computed results only.").classes("text-secondary text-caption")
```

---

### `scripts/export_results.py` — NEW: regenerate all results

Owner runs this after updating data/notebooks. Outputs go into `results/` and are committed to git.

```python
"""
Export pre-computed results for public distribution.

Usage (owner only — requires data/ and tvkit credentials):
    uv run python scripts/export_results.py

What this does:
    1. Convert all notebooks to static HTML  →  results/notebooks/*.html
    2. Run latest backtest                   →  results/backtest/*.json
    3. Export latest signal ranking          →  results/signals/latest_ranking.json

After running:
    git add results/
    git commit -m "results: update pre-computed outputs YYYY-MM-DD"
    git push
"""

import asyncio
import json
import subprocess
from pathlib import Path

from csm.config.settings import settings
from csm.research.backtest import MomentumBacktest, BacktestConfig
from csm.data.store import ParquetStore

NOTEBOOKS_DIR = Path("notebooks")
RESULTS_DIR = Path("results")


def export_notebooks() -> None:
    """Convert .ipynb to static HTML (no kernel, no outputs stripped)."""
    for nb in sorted(NOTEBOOKS_DIR.glob("*.ipynb")):
        out = RESULTS_DIR / "notebooks" / nb.with_suffix(".html").name
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "uv", "run", "jupyter", "nbconvert",
            "--to", "html",
            "--no-input",           # hide code cells in output (optional — remove to show code)
            "--execute",            # re-execute notebook before export
            "--output", str(out),
            str(nb),
        ], check=True)
        print(f"  exported: {out}")


async def export_backtest() -> None:
    """Run canonical backtest config and save results JSON."""
    store = ParquetStore(settings.data_dir / "processed")
    bt = MomentumBacktest(store=store)
    config = BacktestConfig(
        formation_months=12,
        skip_months=1,
        top_quantile=0.2,
        weight_scheme="equal",
    )
    result = await bt.run(config=config)

    out_dir = RESULTS_DIR / "backtest"
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "summary.json").write_text(
        json.dumps(result.metrics_dict(), indent=2, ensure_ascii=False)
    )
    (out_dir / "equity_curve.json").write_text(
        json.dumps(result.equity_curve_dict(), indent=2, ensure_ascii=False)
    )
    (out_dir / "annual_returns.json").write_text(
        json.dumps(result.annual_returns_dict(), indent=2, ensure_ascii=False)
    )
    print(f"  exported: {out_dir}")


async def export_signals() -> None:
    """Export latest signal ranking (no raw prices)."""
    store = ParquetStore(settings.data_dir / "processed")
    # Load latest feature matrix and rank
    from csm.features.pipeline import FeaturePipeline
    from csm.research.ranking import CrossSectionalRanker

    pipeline = FeaturePipeline(store=store)
    ranker = CrossSectionalRanker()
    feature_matrix = pipeline.load_latest()
    ranked = ranker.rank(feature_matrix, date=feature_matrix.index.get_level_values("date").max())

    out = RESULTS_DIR / "signals" / "latest_ranking.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(ranked.to_json(orient="records", indent=2, force_ascii=False))
    print(f"  exported: {out}")


if __name__ == "__main__":
    print("Exporting notebooks...")
    export_notebooks()

    print("Exporting backtest results...")
    asyncio.run(export_backtest())

    print("Exporting signal ranking...")
    asyncio.run(export_signals())

    print("\nDone. Commit results/ to git:")
    print('  git add results/ && git commit -m "results: update YYYY-MM-DD"')
```

---

### `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first (layer cache)
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev

# Copy source
COPY src/ ./src/
COPY api/ ./api/
COPY ui/ ./ui/
COPY results/ ./results/

ENV CSM_PUBLIC_MODE=true
ENV CSM_DATA_DIR=/app/data
ENV PYTHONPATH=/app/src

EXPOSE 8000 8080

CMD ["uv", "run", "python", "ui/main.py"]
```

---

### `docker-compose.yml` — Public mode (default for anyone who clones)

```yaml
services:
  csm:
    build: .
    ports:
      - "8080:8080"   # NiceGUI dashboard
      - "8000:8000"   # FastAPI (optional — for direct API access)
    environment:
      CSM_PUBLIC_MODE: "true"
      CSM_LOG_LEVEL: "INFO"
    volumes:
      - ./results:/app/results:ro   # read-only — public can't overwrite
    restart: unless-stopped
```

---

### `docker-compose.private.yml` — Override for owner

```yaml
# Owner usage:
#   docker compose -f docker-compose.yml -f docker-compose.private.yml up
services:
  csm:
    environment:
      CSM_PUBLIC_MODE: "false"
      TVKIT_BROWSER: "chrome"
    volumes:
      - ./data:/app/data             # mount live data directory
      - ./results:/app/results       # writable — can export new results
      - ~/.config/google-chrome:/root/.config/google-chrome:ro  # tvkit browser auth
```

---

## .gitignore Additions

```gitignore
# Data — never commit raw or processed market data
data/raw/
data/processed/
data/universe/

# Environment
.env
.env.*
!.env.example

# results/ IS committed — do not ignore
# Exception: temporary export artifacts
results/.tmp/
```

---

## README Section to Add

### Public Mode

This repository ships with pre-computed research outputs in `results/`.
You do not need a TradingView account or market data subscription to view the research.

```bash
# Clone and run — no credentials needed
git clone https://github.com/lumduan/csm-set
cd csm-set
docker compose up
# → open http://localhost:8080
```

**What you will see:**
- Static HTML notebooks: signal research, backtest analysis, portfolio optimization
- Pre-computed backtest equity curve and performance metrics
- Latest momentum signal rankings (symbol + quintile + score, no raw prices)

**What requires credentials (owner only):**
- Fetching live OHLCV data via tvkit
- Re-running notebooks against fresh data
- Generating new signal rankings

Raw market data is sourced from TradingView via [tvkit](https://github.com/lumduan/tvkit)
and is subject to TradingView's terms of service. It is not distributed with this repository.

---

## Owner Workflow — Updating Results

```bash
# 1. Fetch latest data (requires tvkit credentials in .env)
uv run python scripts/fetch_history.py

# 2. Run notebooks and export to results/
uv run python scripts/export_results.py

# 3. Commit and push — public users get updated research
git add results/
git commit -m "results: update signal research and backtest 2025-Q1"
git push
```

---

## Data Boundary Summary

| Data type | In repo? | Reasoning |
|---|---|---|
| Raw OHLCV parquet | No | TradingView copyright |
| Adjusted prices | No | Derived from raw — same restriction |
| Universe symbol lists with prices | No | Contains price data |
| NAV index series (100-based) | Yes | Relative returns, no absolute prices |
| Signal z-scores and quintiles | Yes | Derived scores, no prices |
| Notebook HTML (no-input mode) | Yes | Research output, no raw data visible |
| Code (all modules) | Yes | MIT licensed |
| tvkit credentials | No | Personal — .env only |
