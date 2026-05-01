"""RFC 7807 problem-detail error response schema."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProblemDetail(BaseModel):
    """RFC 7807 application/problem+json response body.

    Fields ``type``, ``title``, and ``status`` carry defaults so existing code that
    constructs ``ProblemDetail(detail=..., request_id=...)`` continues to work.  The
    global exception handlers always populate the full RFC 7807 set.
    """

    model_config = ConfigDict(frozen=True)

    type: str = Field(
        default="about:blank",
        description="URI identifying the problem type",
        examples=["tag:csm-set,2026:problem/snapshot-not-found"],
    )
    title: str = Field(
        default="",
        description="Short human-readable problem summary",
        examples=["Universe snapshot not found"],
    )
    status: int = Field(
        default=0,
        description="HTTP status code echoed in the body",
        examples=[404],
    )
    detail: str = Field(description="Human-readable explanation specific to this occurrence")
    instance: str | None = Field(
        default=None,
        description="Request path that triggered the error",
        examples=["/api/v1/universe"],
    )
    request_id: str | None = Field(
        default=None,
        description="Unique request identifier for log correlation",
    )
