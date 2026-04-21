"""Signals page for csm-set."""

import httpx
import pandas as pd
from nicegui import ui

from api.main import app
from ui.components.tables import signal_table


async def _fetch_signals() -> dict[str, object]:
    transport: httpx.ASGITransport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://app") as client:
        response: httpx.Response = await client.get("/api/v1/signals/latest")
        response.raise_for_status()
        return dict(response.json())


@ui.page("/signals")
async def signals_page() -> None:
    """Render the latest signal rankings."""

    payload: dict[str, object] = await _fetch_signals()
    rankings_data: object = payload.get("rankings", [])
    rankings: pd.DataFrame = pd.DataFrame(rankings_data if isinstance(rankings_data, list) else [])
    ui.label("Latest Signals").classes("text-3xl font-bold")
    ui.label(f"As of: {payload.get('as_of', 'n/a')}")
    if not rankings.empty:
        signal_table(rankings)
        numeric_columns: list[str] = [column for column in ["z_score", "rank"] if column in rankings.columns]
        if numeric_columns:
            heatmap_data: list[list[object]] = []
            for row_index, (_, row) in enumerate(rankings.head(20).iterrows()):
                for column_index, column_name in enumerate(numeric_columns):
                    heatmap_data.append([column_index, row_index, float(row[column_name])])
            ui.echart(
                {
                    "xAxis": {"type": "category", "data": numeric_columns},
                    "yAxis": {"type": "category", "data": rankings.head(20)["symbol"].tolist()},
                    "visualMap": {"min": -3, "max": 3, "orient": "horizontal"},
                    "series": [{"type": "heatmap", "data": heatmap_data}],
                }
            ).classes("w-full h-[30rem]")
    else:
        ui.label("No signal rankings available.")
