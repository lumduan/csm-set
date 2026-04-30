"""Backtest endpoint response schemas.

BacktestConfig from src.csm.research.backtest is used directly as the
request body — no wrapper needed.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BacktestRunResponse(BaseModel):
    """Response from submitting a backtest run."""

    job_id: str = Field(description="UUID of the submitted job")
    status: str = Field(
        description="Initial job status",
        examples=["accepted"],
    )
