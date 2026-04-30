"""Error response schemas.

Matches the Phase 5.1 exception handler shape.  Full RFC 7807
problem-details (type, title, status, instance) land in Phase 5.8.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProblemDetail(BaseModel):
    """API error response body."""

    model_config = ConfigDict(frozen=True)

    detail: str = Field(description="Human-readable error description")
    request_id: str = Field(description="Unique request identifier for log correlation")
