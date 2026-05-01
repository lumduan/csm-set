"""Data refresh endpoint response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from api.jobs import JobStatus


class RefreshResult(BaseModel):
    """Response returned immediately after submitting a data refresh job."""

    job_id: str = Field(description="ULID of the submitted refresh job")
    status: JobStatus = Field(description="Initial job status (always 'accepted')")
