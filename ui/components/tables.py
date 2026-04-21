"""Tabular UI components for csm-set."""

import pandas as pd
from nicegui import ui


def signal_table(df: pd.DataFrame) -> None:
    """Render sortable NiceGUI ag-grid table for signal rankings."""

    ui.aggrid(
        {
            "defaultColDef": {"sortable": True, "filter": True, "resizable": True},
            "columnDefs": [{"field": column} for column in df.columns],
            "rowData": df.to_dict(orient="records"),
        }
    ).classes("w-full h-96")


def portfolio_table(df: pd.DataFrame) -> None:
    """Render portfolio holdings table with weight bar per row."""

    table_frame: pd.DataFrame = df.copy()
    if "weight" in table_frame.columns:
        table_frame["weight_pct"] = (table_frame["weight"].astype(float) * 100.0).round(2)
    ui.aggrid(
        {
            "defaultColDef": {"sortable": True, "filter": True, "resizable": True},
            "columnDefs": [{"field": column} for column in table_frame.columns],
            "rowData": table_frame.to_dict(orient="records"),
        }
    ).classes("w-full h-96")
