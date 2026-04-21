"""FastAPI application entrypoint for csm-set."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import Response
from fastapi.staticfiles import StaticFiles

from api.deps import set_store
from api.routers import backtest_router, data_router, portfolio_router, signals_router, universe_router
from api.scheduler.jobs import create_scheduler
from csm.config.settings import settings
from csm.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)
WRITE_PATHS: set[str] = {"/api/v1/data/refresh", "/api/v1/backtest/run"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise shared services and owner-side scheduler."""

    store: ParquetStore = ParquetStore(settings.data_dir / "processed")
    set_store(store)
    scheduler = create_scheduler(settings=settings, store=store)
    app.state.store = store
    app.state.scheduler = scheduler
    if scheduler is not None:
        scheduler.start()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


app: FastAPI = FastAPI(title="CSM-SET API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount(
    "/static/notebooks",
    StaticFiles(directory=settings.results_dir / "notebooks"),
    name="notebooks",
)


@app.middleware("http")
async def public_mode_guard(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Block write endpoints in public mode before they hit routers."""

    if settings.public_mode and request.url.path in WRITE_PATHS:
        return JSONResponse(
            {"detail": "Disabled in public mode. Set CSM_PUBLIC_MODE=false to enable."},
            status_code=403,
        )
    return await call_next(request)


app.include_router(universe_router, prefix="/api/v1")
app.include_router(signals_router, prefix="/api/v1")
app.include_router(portfolio_router, prefix="/api/v1")
app.include_router(backtest_router, prefix="/api/v1")
app.include_router(data_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict[str, object]:
    """Return a simple service health payload."""

    return {"status": "ok", "version": "0.1.0", "public_mode": settings.public_mode}


__all__: list[str] = ["app"]