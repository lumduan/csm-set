"""Scheduler management endpoints — manual job trigger."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import get_adapter_manager, get_jobs, get_settings, get_store
from api.jobs import JobKind, JobRegistry
from api.logging import get_request_id
from api.scheduler.jobs import daily_refresh
from api.schemas.data import RefreshResult
from api.schemas.errors import ProblemDetail
from csm.config.settings import Settings
from csm.data.store import ParquetStore

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(prefix="/scheduler", tags=["scheduler"])

_VALID_JOB_IDS: frozenset[str] = frozenset({"daily_refresh"})


@router.post(
    "/run/{job_id}",
    response_model=RefreshResult,
    summary="Trigger a scheduler job manually",
    description=(
        "Manually trigger a scheduler job by its ID. "
        "Returns a job ID immediately — poll ``GET /api/v1/jobs/{job_id}`` "
        "for completion status. Blocked in public mode."
    ),
    responses={
        200: {"description": "Job triggered"},
        400: {
            "description": "Invalid or unknown job_id",
            "model": ProblemDetail,
        },
        403: {
            "description": "Disabled in public mode",
            "model": ProblemDetail,
        },
    },
)
async def trigger_job(
    job_id: str,
    request: Request,
    jobs: JobRegistry = Depends(get_jobs),
    settings: Settings = Depends(get_settings),
    store: ParquetStore = Depends(get_store),
) -> RefreshResult:
    """Manually trigger a scheduler job and return a job tracking ID."""
    if job_id not in _VALID_JOB_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown job_id {job_id!r}. Valid values: {sorted(_VALID_JOB_IDS)}",
        )

    adapters = get_adapter_manager(request)
    record = await jobs.submit(
        JobKind.DATA_REFRESH,
        daily_refresh,
        request_id=get_request_id(),
        settings=settings,
        store=store,
        adapters=adapters,
    )
    logger.info("Manual trigger for scheduler job %r submitted as %s", job_id, record.job_id)
    return RefreshResult(job_id=record.job_id, status=record.status)
