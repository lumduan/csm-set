"""Job status polling endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_jobs
from api.jobs import JobKind, JobRecord, JobRegistry, JobStatus
from api.schemas.errors import ProblemDetail

logger: logging.Logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get(
    "/{job_id}",
    response_model=JobRecord,
    summary="Get job status",
    description=(
        "Return the current state of a submitted job by its ULID. "
        "Available in both public and private modes (returns 404 in "
        "public mode since no jobs are ever created)."
    ),
    responses={
        200: {"description": "Job record found"},
        404: {"description": "Job ID not found", "model": ProblemDetail},
    },
)
async def get_job(
    job_id: str,
    jobs: JobRegistry = Depends(get_jobs),
) -> JobRecord:
    """Return the job record for *job_id*."""
    record: JobRecord | None = jobs.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
    return record


@router.get(
    "",
    response_model=list[JobRecord],
    summary="List jobs",
    description=(
        "Return a filtered list of job records, newest first. "
        "Private mode only — returns 403 in public mode."
    ),
    responses={
        200: {"description": "Filtered list of job records"},
        403: {"description": "Disabled in public mode", "model": ProblemDetail},
    },
)
async def list_jobs(
    kind: JobKind | None = Query(None, description="Filter by job kind"),
    status: JobStatus | None = Query(None, description="Filter by job status"),
    limit: int = Query(default=50, ge=1, le=200, description="Maximum number of results"),
    jobs: JobRegistry = Depends(get_jobs),
) -> list[JobRecord]:
    """Return filtered job records, newest first."""
    return jobs.list(kind=kind, status=status, limit=limit)
