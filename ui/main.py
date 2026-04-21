"""NiceGUI entrypoint mounted on the FastAPI application."""

from nicegui import ui

from api.main import app
from csm.config.settings import settings
from ui import pages  # noqa: F401


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        fastapi_app=app,
        port=settings.ui_port,
        title="CSM-SET",
        dark=True,
        favicon="📈",
    )