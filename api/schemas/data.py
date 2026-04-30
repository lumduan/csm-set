"""Data refresh endpoint response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RefreshResult(BaseModel):
    """Result of a data refresh operation."""

    refreshed: int = Field(ge=0, description="Number of symbols successfully refreshed")
    requested: int = Field(ge=0, description="Number of symbols requested")
