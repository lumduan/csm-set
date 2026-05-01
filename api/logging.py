"""Request-ID middleware, structured logging, access logs, and key redaction."""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from datetime import UTC, datetime

from pydantic import SecretStr
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from ulid import ULID

from csm.config.settings import Settings

REQUEST_ID_CTX: ContextVar[str] = ContextVar("request_id", default="N/A")

REDACTED: str = "***REDACTED***"

LOGGING_INTERNALS: frozenset[str] = frozenset(
    {
        "name",
        "levelno",
        "levelname",
        "pathname",
        "filename",
        "module",
        "funcName",
        "lineno",
        "exc_info",
        "exc_text",
        "args",
        "msg",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "stack_info",
    }
)


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


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record.

    Every record includes ``ts``, ``level``, ``logger``, ``msg``, and
    ``request_id`` (from the context variable).  Fields passed via
    ``logger.info("msg", extra={...})`` are merged into the JSON object.
    ``request_id`` from the contextvar always wins over an extra field of the
    same name.
    """

    def format(self, record: logging.LogRecord) -> str:
        obj: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": get_request_id(),
        }
        for key, value in record.__dict__.items():
            if key in LOGGING_INTERNALS:
                continue
            if key == "request_id":
                continue
            obj[key] = value
        if record.exc_info and record.exc_info[1]:
            obj["exc"] = str(record.exc_info[1])
        return json.dumps(obj, default=str)


def configure_logging(settings: Settings) -> None:
    """Configure structured JSON logging for the application.

    Sets the root logger level from *settings.log_level*, replaces all root
    handlers with a single :class:`JsonFormatter`-equipped
    :class:`~logging.StreamHandler`, and silences the ``uvicorn.access``
    logger so our :class:`AccessLogMiddleware` is the canonical source of
    access log lines.
    """

    level: int = getattr(logging, settings.log_level.upper(), logging.INFO)
    root: logging.Logger = logging.getLogger()
    root.setLevel(level)

    root.handlers = [h for h in root.handlers if type(h) is not logging.StreamHandler]
    handler: logging.StreamHandler = logging.StreamHandler(sys.stderr)  # type: ignore[type-arg]
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    uvicorn_access: logging.Logger = logging.getLogger("uvicorn.access")
    uvicorn_access.handlers.clear()
    uvicorn_access.propagate = False

    logging.getLogger(__name__).info("Logging configured", extra={"log_level": settings.log_level})


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Emit one structured access-log line per request.

    Must be placed inside :class:`RequestIDMiddleware` so the request-id
    context variable is set.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started: float = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms: float = round((time.perf_counter() - started) * 1000, 3)
        client_ip: str = request.client.host if request.client else "N/A"
        logging.getLogger(__name__).info(
            "access",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "client_ip": client_ip,
            },
        )
        return response


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
                a.replace(self._secret, REDACTED) if isinstance(a, str) and self._secret in a else a
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
    "AccessLogMiddleware",
    "JsonFormatter",
    "KeyRedactionFilter",
    "RequestIDMiddleware",
    "configure_logging",
    "get_request_id",
    "install_key_redaction",
]
