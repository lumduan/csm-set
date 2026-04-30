"""Stub exception handlers for the csm-set API.

Full RFC 7807 problem-details handler lands in Phase 5.8.
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from api.logging import get_request_id

logger: logging.Logger = logging.getLogger(__name__)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "request_id": get_request_id(),
        },
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "request_id": get_request_id(),
        },
    )


__all__: list[str] = ["general_exception_handler", "http_exception_handler"]
