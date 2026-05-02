"""FastAPI application entrypoint for csm-set."""

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.responses import Response

from api.deps import set_store
from api.errors import (
    general_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from api.jobs import JobRegistry, JobStatus
from api.logging import (
    AccessLogMiddleware,
    RequestIDMiddleware,
    configure_logging,
    get_request_id,
    install_key_redaction,
)
from api.routers import (
    backtest_router,
    data_router,
    jobs_router,
    notebooks_router,
    portfolio_router,
    scheduler_router,
    signals_router,
    universe_router,
)
from api.scheduler.jobs import create_scheduler
from api.schemas.health import HealthStatus
from api.security import APIKeyMiddleware
from api.static_files import NotebookStaticFiles
from csm import __version__
from csm.config.settings import settings
from csm.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)
WRITE_PATHS: set[str] = {
    "/api/v1/data/refresh",
    "/api/v1/backtest/run",
    "/api/v1/jobs",
    "/api/v1/scheduler/run/daily_refresh",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise shared services, structured logging, and owner-side scheduler."""

    configure_logging(settings)
    install_key_redaction(settings.api_key)
    if not settings.public_mode and settings.api_key is None:
        logger.warning(
            "CSM_API_KEY is not configured; private-mode auth is DISABLED. "
            "Set CSM_API_KEY before exposing this API beyond loopback."
        )

    store: ParquetStore = ParquetStore(settings.data_dir / "processed")
    set_store(store)

    jobs_persistence_dir = settings.results_dir / ".tmp" / "jobs"
    jobs = JobRegistry.load_all(jobs_persistence_dir)
    app.state.jobs = jobs

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
        await jobs.shutdown()


app: FastAPI = FastAPI(title="CSM-SET API", version=__version__, lifespan=lifespan)

# Middleware registration is LIFO via insert(0, ...) — the LAST registered ends
# up OUTERMOST in the runtime stack.  Desired runtime order, outermost first:
#   RequestIDMiddleware → AccessLogMiddleware → APIKeyMiddleware →
#   public_mode_guard → CORSMiddleware → routers
# RequestID must be outermost so the request_id contextvar is set before the
# auth layer, access-log middleware, or public-mode guard build their responses.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def public_mode_guard(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Block write endpoints in public mode before they hit routers."""

    if settings.public_mode and request.url.path in WRITE_PATHS:
        return JSONResponse(
            content={
                "type": "tag:csm-set,2026:problem/public-mode-disabled",
                "title": "Public mode — read only",
                "status": 403,
                "detail": "Disabled in public mode. Set CSM_PUBLIC_MODE=false to enable.",
                "instance": request.url.path,
                "request_id": get_request_id(),
            },
            status_code=403,
            headers={"Content-Type": "application/problem+json"},
        )
    return await call_next(request)


app.add_middleware(APIKeyMiddleware)
app.add_middleware(AccessLogMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(Exception, general_exception_handler)
app.mount(
    "/static/notebooks",
    NotebookStaticFiles(),
    name="notebooks",
)


app.include_router(universe_router, prefix="/api/v1")
app.include_router(signals_router, prefix="/api/v1")
app.include_router(portfolio_router, prefix="/api/v1")
app.include_router(backtest_router, prefix="/api/v1")
app.include_router(data_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(notebooks_router, prefix="/api/v1")
app.include_router(scheduler_router, prefix="/api/v1")


@app.get(
    "/health",
    response_model=HealthStatus,
    summary="Service health check",
    description=(
        "Return service status, application version, public-mode flag, "
        "scheduler status, last-refresh information, and pending job count."
    ),
    responses={
        200: {
            "description": "Service health information",
            "content": {
                "application/json": {
                    "example": {
                        "status": "ok",
                        "version": "0.1.0",
                        "public_mode": False,
                        "scheduler_running": True,
                        "last_refresh_at": "2026-04-30T10:00:00Z",
                        "last_refresh_status": "succeeded",
                        "jobs_pending": 0,
                    },
                },
            },
        },
    },
)
async def health(request: Request) -> HealthStatus:
    """Return extended service health information."""

    scheduler = getattr(request.app.state, "scheduler", None)
    scheduler_running: bool = scheduler is not None

    last_refresh_at: datetime | None = None
    last_refresh_status: str | None = None
    marker_path = settings.results_dir / ".tmp" / "last_refresh.json"
    if marker_path.exists():
        try:
            marker_data = json.loads(marker_path.read_text(encoding="utf-8"))
            ts_str: str | None = marker_data.get("timestamp")
            if ts_str:
                last_refresh_at = datetime.fromisoformat(ts_str)
            failures: int = marker_data.get("failures", 0)
            last_refresh_status = "failed" if failures > 0 else "succeeded"
        except (json.JSONDecodeError, OSError, ValueError):
            logger.warning("Failed to parse last_refresh.json", exc_info=True)

    jobs = getattr(request.app.state, "jobs", None)
    jobs_pending: int = 0
    if jobs is not None:
        jobs_pending = len(jobs.list(status=JobStatus.ACCEPTED))

    is_private: bool = not settings.public_mode
    is_degraded: bool = (is_private and not scheduler_running) or (last_refresh_status == "failed")

    return HealthStatus(
        status="degraded" if is_degraded else "ok",
        version=__version__,
        public_mode=settings.public_mode,
        scheduler_running=scheduler_running,
        last_refresh_at=last_refresh_at,
        last_refresh_status=last_refresh_status,  # type: ignore[arg-type]
        jobs_pending=jobs_pending,
    )


__all__: list[str] = ["app"]
