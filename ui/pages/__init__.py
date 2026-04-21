"""Page registration for the NiceGUI frontend."""

from ui.pages.backtest import backtest_page
from ui.pages.dashboard import dashboard_page
from ui.pages.notebooks import notebooks_page
from ui.pages.signals import signals_page
from ui.pages.universe import universe_page

__all__: list[str] = [
    "backtest_page",
    "dashboard_page",
    "notebooks_page",
    "signals_page",
    "universe_page",
]