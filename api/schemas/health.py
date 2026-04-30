"""Health endpoint response schemas.

Extended with scheduler_running, last_refresh_at, etc. in Phase 5.8.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class HealthStatus(BaseModel):
    """Service health information."""

    model_config = ConfigDict(frozen=True)

    status: str = Field(
        description="Service status",
        examples=["ok"],
    )
    version: str = Field(description="Application version")
    public_mode: bool = Field(description="Whether the API is in public (read-only) mode")
