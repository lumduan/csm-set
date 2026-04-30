"""Request-ID middleware and structured logging for the csm-set API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from ulid import ULID

REQUEST_ID_CTX: ContextVar[str] = ContextVar("request_id", default="N/A")


def get_request_id() -> str:
    """Return the current request ID from the context variable."""
    return REQUEST_ID_CTX.get()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assign a ULID to every request and echo it in the X-Request-ID header."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id: str = str(ULID())
        token: Token[str] = REQUEST_ID_CTX.set(request_id)
        try:
            response: Response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            REQUEST_ID_CTX.reset(token)


__all__: list[str] = ["REQUEST_ID_CTX", "RequestIDMiddleware", "get_request_id"]
