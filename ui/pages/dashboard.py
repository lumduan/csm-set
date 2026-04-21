"""Dashboard page for csm-set."""

import asyncio
import json
from pathlib import Path

import httpx
import pandas as pd
from nicegui import ui

from api.main import app
from csm.config.settings import settings
from csm.risk.regime import RegimeState


async def _get_json(path: str) -> dict[str, object]:
    transport: httpx.ASGITransport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://app") as client:
        response: httpx.Response = await client.get(path)
        response.raise_for_status()
        return dict(response.json())


@ui.page("/")
async def dashboard_page() -> None:
    """Render the main dashboard page."""

    ui.label("CSM-SET Dashboard").classes("text-3xl font-bold")
    if settings.public_mode:
        with ui.card().classes("w-full bg-amber-200 text-black"):
            ui.label("Read-only mode - displaying pre-computed results. No live data.")

    summary: dict[str, object] = {}
    summary_path: Path = settings.results_dir / "backtest" / "summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())

    regime_text: str = str(summary.get("regime", RegimeState.NEUTRAL.value))
    color: str = "green" if regime_text == RegimeState.BULL.value else "red" if regime_text == RegimeState.BEAR.value else "amber"
    ui.badge(regime_text).props(f"color={color}")

    with ui.row().classes("w-full gap-4"):
        with ui.card().classes("w-80"):
            ui.label("Portfolio Snapshot").classes("text-xl")
            ui.label(f"Symbol count: {summary.get('symbol_count', 0)}")
            ui.label(f"Weight sum: {summary.get('weight_sum', 1.0)}")
            ui.label(f"Last rebalance: {summary.get('last_rebalance_date', 'n/a')}")

        with ui.card().classes("flex-1"):
            ui.label("Navigation").classes("text-xl")
            with ui.row().classes("gap-2"):
                ui.link("Signals", "/signals")
                ui.link("Backtest", "/backtest")
                ui.link("Notebooks", "/notebooks")
                ui.link("Universe", "/universe")
            if not settings.public_mode:
                ui.button("Refresh Data", on_click=lambda: ui.notify("Use the API to refresh data."))

    if not settings.public_mode:
        series_index: pd.DatetimeIndex = pd.date_range(end=pd.Timestamp.now(), periods=30, freq="D")
        index_values: pd.Series = pd.Series(range(30), index=series_index, dtype=float)
        with ui.card().classes("w-full"):
            ui.label("SET Index - Last 30 Days")
            ui.echart(
                {
                    "xAxis": {"type": "category", "data": [str(index.date()) for index in series_index]},
                    "yAxis": {"type": "value"},
                    "series": [{"type": "line", "data": index_values.astype(float).tolist()}],
                }
            ).classes("w-full h-64")

    await asyncio.sleep(0)
