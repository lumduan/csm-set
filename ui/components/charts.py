"""Chart components for the NiceGUI frontend."""

import pandas as pd
from nicegui import ui


def equity_curve_chart(equity: pd.Series, benchmark: pd.Series | None = None) -> None:
    """Render equity curve (NAV) chart via NiceGUI plotly integration."""

    series: list[dict[str, object]] = [
        {
            "type": "line",
            "name": "Portfolio",
            "data": [[str(index), float(value)] for index, value in equity.items()],
        }
    ]
    if benchmark is not None:
        series.append(
            {
                "type": "line",
                "name": "Benchmark",
                "data": [[str(index), float(value)] for index, value in benchmark.items()],
            }
        )
    ui.echart({"xAxis": {"type": "time"}, "yAxis": {"type": "value"}, "series": series}).classes(
        "w-full h-80"
    )


def ic_chart(ic_series: pd.Series) -> None:
    """Render IC time series bar chart (green positive, red negative)."""

    data: list[dict[str, object]] = [
        {
            "value": [str(index), float(value)],
            "itemStyle": {"color": "#16a34a" if float(value) >= 0.0 else "#dc2626"},
        }
        for index, value in ic_series.items()
    ]
    ui.echart(
        {
            "xAxis": {"type": "time"},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar", "data": data}],
        }
    ).classes("w-full h-64")


def drawdown_chart(underwater: pd.Series) -> None:
    """Render underwater equity curve as filled area chart."""

    ui.echart(
        {
            "xAxis": {"type": "time"},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "line",
                    "areaStyle": {},
                    "data": [[str(index), float(value)] for index, value in underwater.items()],
                }
            ],
        }
    ).classes("w-full h-64")
