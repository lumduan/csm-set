"""Universe page for csm-set."""

import httpx
import pandas as pd
from api.main import app
from nicegui import ui


async def _fetch_universe() -> dict[str, object]:
    transport: httpx.ASGITransport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://app") as client:
        response: httpx.Response = await client.get("/api/v1/universe")
        if response.status_code == 404:
            return {"items": []}
        response.raise_for_status()
        return dict(response.json())


@ui.page("/universe")
async def universe_page() -> None:
    """Render a filterable and sortable universe table."""

    payload: dict[str, object] = await _fetch_universe()
    rows: object = payload.get("items", [])
    frame: pd.DataFrame = pd.DataFrame(rows if isinstance(rows, list) else [])
    ui.label("Current Universe").classes("text-3xl font-bold")
    if frame.empty:
        ui.label("No stored universe snapshot available.")
        return
    ui.aggrid(
        {
            "defaultColDef": {"sortable": True, "filter": True, "resizable": True},
            "columnDefs": [{"field": column} for column in frame.columns],
            "rowData": frame.to_dict(orient="records"),
        }
    ).classes("w-full h-[36rem]")
