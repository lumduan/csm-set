"""Backtest endpoint response schemas.

BacktestConfig from src.csm.research.backtest is used directly as the
request body — no wrapper needed.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from api.jobs import JobStatus


class BacktestRunResponse(BaseModel):
    """Response returned immediately after submitting a backtest run."""

    job_id: str = Field(description="ULID of the submitted job")
    status: JobStatus = Field(description="Initial job status (always 'accepted')")
