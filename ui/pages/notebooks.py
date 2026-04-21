"""Tabbed viewer for pre-computed static HTML notebook exports."""

from pathlib import Path

from nicegui import ui

from csm.config.settings import settings

NOTEBOOKS: list[tuple[str, str]] = [
    ("01 - Data Exploration", "01_data_exploration.html"),
    ("02 - Signal Research", "02_signal_research.html"),
    ("03 - Backtest Analysis", "03_backtest_analysis.html"),
    ("04 - Portfolio Optimization", "04_portfolio_optimization.html"),
]


@ui.page("/notebooks")
def notebooks_page() -> None:
    """Render tabs for exported notebook HTML files."""

    ui.label("Research Notebooks").classes("text-3xl font-bold")
    with ui.tabs().classes("w-full") as tabs:
        for title, _ in NOTEBOOKS:
            ui.tab(title)
    with ui.tab_panels(tabs, value=NOTEBOOKS[0][0]).classes("w-full"):
        for title, filename in NOTEBOOKS:
            html_path: Path = settings.results_dir / "notebooks" / filename
            content: str = html_path.read_text() if html_path.exists() else ""
            with ui.tab_panel(title):
                if "Placeholder" in content or not html_path.exists():
                    with ui.card().classes("w-full"):
                        ui.label(title).classes("text-xl")
                        ui.label("This notebook export is still a placeholder.")
                        ui.label("Run scripts/export_results.py in private mode to generate the HTML output.")
                else:
                    ui.html(
                        f'<iframe src="/static/notebooks/{filename}" style="width:100%;height:85vh;border:none;"></iframe>'
                    )
