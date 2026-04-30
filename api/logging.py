"""Request-ID middleware, structured logging, and key redaction for the csm-set API."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token

from pydantic import SecretStr
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from ulid import ULID

REQUEST_ID_CTX: ContextVar[str] = ContextVar("request_id", default="N/A")

REDACTED: str = "***REDACTED***"


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


class KeyRedactionFilter(logging.Filter):
    """Replace the configured API key with ``***REDACTED***`` in log records.

    Scans ``record.msg`` and any string entries in ``record.args``. Empty
    secrets short-circuit so the filter is a no-op when no key is configured.
    """

    def __init__(self, secret: str) -> None:
        super().__init__()
        self._secret: str = secret

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secret:
            return True

        if isinstance(record.msg, str) and self._secret in record.msg:
            record.msg = record.msg.replace(self._secret, REDACTED)

        if record.args:
            args = record.args if isinstance(record.args, tuple) else (record.args,)
            redacted_args: tuple[object, ...] = tuple(
                a.replace(self._secret, REDACTED)
                if isinstance(a, str) and self._secret in a
                else a
                for a in args
            )
            record.args = redacted_args

        return True


def install_key_redaction(secret: SecretStr | None) -> None:
    """Attach a :class:`KeyRedactionFilter` to the root logger when a key is set.

    No-op when ``secret is None`` so the dev-mode pass-through path adds zero
    overhead.
    """

    if secret is None:
        return
    raw: str = secret.get_secret_value()
    if not raw:
        return
    logging.getLogger().addFilter(KeyRedactionFilter(raw))


__all__: list[str] = [
    "REDACTED",
    "REQUEST_ID_CTX",
    "KeyRedactionFilter",
    "RequestIDMiddleware",
    "get_request_id",
    "install_key_redaction",
]
