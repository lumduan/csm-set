"""Backtest page for csm-set."""

import json
from pathlib import Path

import httpx
import pandas as pd
from api.main import app
from nicegui import ui

from csm.config.settings import settings
from ui.components.charts import equity_curve_chart


async def _post_backtest(config: dict[str, object]) -> dict[str, object]:
    transport: httpx.ASGITransport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://app") as client:
        response: httpx.Response = await client.post("/api/v1/backtest/run", json=config)
        response.raise_for_status()
        return dict(response.json())


@ui.page("/backtest")
async def backtest_page() -> None:
    """Render backtest results or private-mode controls."""

    ui.label("Backtest Analysis").classes("text-3xl font-bold")
    if settings.public_mode:
        summary_path: Path = settings.results_dir / "backtest" / "summary.json"
        curve_path: Path = settings.results_dir / "backtest" / "equity_curve.json"
        annual_path: Path = settings.results_dir / "backtest" / "annual_returns.json"
        summary: dict[str, object] = (
            json.loads(summary_path.read_text()) if summary_path.exists() else {}
        )
        curve_payload: dict[str, object] = (
            json.loads(curve_path.read_text()) if curve_path.exists() else {"series": []}
        )
        annual_payload: dict[str, object] = (
            json.loads(annual_path.read_text()) if annual_path.exists() else {}
        )
        ui.label(f"Pre-computed results - last updated {summary.get('generated_at', 'n/a')}")
        series_payload: object = curve_payload.get("series", [])
        curve_rows: list[dict[str, object]] = (
            [item for item in series_payload if isinstance(item, dict)]
            if isinstance(series_payload, list)
            else []
        )
        equity_map: dict[str, float] = {}
        for item in curve_rows:
            nav_value: object = item.get("nav", 0.0)
            if isinstance(nav_value, (int, float)):
                equity_map[str(item.get("date"))] = float(nav_value)
        equity_series: pd.Series = pd.Series(
            equity_map,
            dtype=float,
        )
        if not equity_series.empty:
            equity_series.index = pd.to_datetime(equity_series.index)
            equity_curve_chart(equity_series)
        with ui.card().classes("w-full"):
            ui.label("Metrics Summary")
            for key, value in summary.items():
                ui.label(f"{key}: {value}")
        annual_df: pd.DataFrame = pd.DataFrame(
            list(annual_payload.items()), columns=["year", "return"]
        )
        if not annual_df.empty:
            ui.echart(
                {
                    "xAxis": {"type": "category", "data": annual_df["year"].tolist()},
                    "yAxis": {"type": "value"},
                    "series": [{"type": "bar", "data": annual_df["return"].astype(float).tolist()}],
                }
            ).classes("w-full h-80")
        return

    formation_months = ui.number("Formation Months", value=12, min=1, max=24)
    skip_months = ui.number("Skip Months", value=1, min=0, max=6)
    top_quantile = ui.number("Top Quantile", value=0.2, min=0.1, max=0.5, step=0.05)
    start_date = ui.input("Start Date", value="2005-01-01")
    end_date = ui.input("End Date", value="2024-12-31")
    weight_scheme = ui.select(
        ["equal", "vol_target", "min_variance"], value="equal", label="Weight Scheme"
    )
    progress = ui.spinner(size="lg").props("color=primary")
    progress.set_visibility(False)

    async def _run() -> None:
        progress.set_visibility(True)
        payload: dict[str, object] = {
            "formation_months": int(formation_months.value),
            "skip_months": int(skip_months.value),
            "top_quantile": float(top_quantile.value),
            "start_date": str(start_date.value),
            "end_date": str(end_date.value),
            "weight_scheme": str(weight_scheme.value),
        }
        result: dict[str, object] = await _post_backtest(payload)
        progress.set_visibility(False)
        ui.notify(f"Backtest job submitted: {result.get('job_id', 'unknown')}")

    ui.button("Run Backtest", on_click=_run)
