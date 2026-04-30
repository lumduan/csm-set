"""Health endpoint response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthStatus(BaseModel):
    """Service health information."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok", "degraded"] = Field(
        description="Service status — 'degraded' when scheduler unavailable or refresh failed",
        examples=["ok"],
    )
    version: str = Field(description="Application version")
    public_mode: bool = Field(description="Whether the API is in public (read-only) mode")
    scheduler_running: bool = Field(
        default=False,
        description="Whether the APScheduler background scheduler is active",
    )
    last_refresh_at: datetime | None = Field(
        default=None,
        description="Timestamp of the most recent daily refresh (UTC)",
    )
    last_refresh_status: Literal["succeeded", "failed"] | None = Field(
        default=None,
        description="Outcome of the most recent daily refresh",
    )
    jobs_pending: int = Field(
        default=0,
        description="Number of jobs in accepted state awaiting execution",
    )
