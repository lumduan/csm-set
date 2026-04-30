"""RFC 7807 problem-detail exception handlers for the csm-set API."""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from api.logging import get_request_id
from api.schemas.errors import ProblemDetail

logger: logging.Logger = logging.getLogger(__name__)

_PROBLEM_BASE: str = "tag:csm-set,2026:problem"

_STATUS_TITLE: dict[int, str] = {
    400: "Bad request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not found",
    405: "Method not allowed",
    409: "Conflict",
    422: "Validation error",
    500: "Internal server error",
}


class ProblemDetailException(HTTPException):
    """Raise inside a handler to produce a specific RFC 7807 response.

    The global :func:`http_exception_handler` detects this type and uses its
    explicit ``type_uri`` and ``title`` instead of mapping from the status code.
    """

    def __init__(self, status_code: int, type_uri: str, title: str, detail: str) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.type_uri: str = type_uri
        self.title: str = title


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Map an HTTPException to an RFC 7807 problem-detail response."""

    if isinstance(exc, ProblemDetailException):
        type_uri: str = exc.type_uri
        title: str = exc.title
        detail: str = exc.detail
        status_code: int = exc.status_code
    else:
        status_code = exc.status_code
        type_uri = _status_type_uri(status_code)
        title = _STATUS_TITLE.get(status_code, "HTTP error")
        detail = str(exc.detail) if exc.detail else ""

    return _problem_response(
        status_code=status_code,
        type_uri=type_uri,
        title=title,
        detail=detail,
        instance=str(request.url.path),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Map a request validation error to an RFC 7807 problem-detail response."""

    errors: list[dict[str, object]] = list(exc.errors())
    detail: str = "Request validation failed"
    if errors:
        first = errors[0]
        raw_loc: object = first.get("loc", [])
        loc = " → ".join(str(p) for p in raw_loc) if isinstance(raw_loc, list) else ""
        msg: str = str(first.get("msg", ""))
        detail = f"{loc}: {msg}" if loc else msg

    return _problem_response(
        status_code=422,
        type_uri=f"{_PROBLEM_BASE}/validation-error",
        title="Validation error",
        detail=detail,
        instance=str(request.url.path),
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map any unhandled exception to a 500 problem-detail response.

    Logs the full traceback at ERROR level. The response body uses a generic
    detail message so internal information is never leaked to the client.
    """

    logger.exception("Unhandled exception")
    return _problem_response(
        status_code=500,
        type_uri=f"{_PROBLEM_BASE}/internal-error",
        title="Internal server error",
        detail="An unexpected error occurred",
        instance=str(request.url.path),
    )


def _problem_response(
    *,
    status_code: int,
    type_uri: str,
    title: str,
    detail: str,
    instance: str,
) -> JSONResponse:
    """Build a JSONResponse with an RFC 7807 ProblemDetail body."""

    return JSONResponse(
        status_code=status_code,
        content=ProblemDetail(
            type=type_uri,
            title=title,
            status=status_code,
            detail=detail,
            instance=instance,
            request_id=get_request_id(),
        ).model_dump(),
        headers={"Content-Type": "application/problem+json"},
    )


def _status_type_uri(status_code: int) -> str:
    """Map an HTTP status code to a problem type URI."""

    mapping: dict[int, str] = {
        401: f"{_PROBLEM_BASE}/unauthorized",
        403: f"{_PROBLEM_BASE}/public-mode-disabled",
        404: f"{_PROBLEM_BASE}/not-found",
        405: f"{_PROBLEM_BASE}/method-not-allowed",
        409: f"{_PROBLEM_BASE}/conflict",
        422: f"{_PROBLEM_BASE}/validation-error",
    }
    return mapping.get(status_code, f"{_PROBLEM_BASE}/http-error")


__all__: list[str] = [
    "ProblemDetailException",
    "general_exception_handler",
    "http_exception_handler",
    "validation_exception_handler",
]
