"""API-key authentication middleware for the csm-set FastAPI surface.

Phase 5.7 — auth is enforced exclusively at the middleware layer. Routers are
unaware of the header and never depend on it. The middleware is a no-op in
public mode (read endpoints stay public; writes are blocked by the existing
``public_mode_guard``) and a no-op in private mode when ``Settings.api_key`` is
unset (dev-mode pass-through; the lifespan emits one WARNING at startup).

When a key is configured, requests to ``PROTECTED_PATHS`` or to any non-GET
``/api/v1/*`` endpoint must carry ``X-API-Key`` matching the configured value
(constant-time comparison via :func:`secrets.compare_digest`). Missing or
invalid headers return ``401`` with a :class:`api.schemas.errors.ProblemDetail`
shaped body that includes the request id from the contextvar.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from api.logging import get_request_id
from csm.config.settings import Settings

logger: logging.Logger = logging.getLogger(__name__)

PROTECTED_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/data/refresh",
        "/api/v1/backtest/run",
        "/api/v1/jobs",
        "/api/v1/scheduler/run/daily_refresh",
    }
)

API_KEY_HEADER: str = "X-API-Key"


def is_protected_path(method: str, path: str) -> bool:
    """Return True if the (method, path) pair requires auth in private mode.

    Protected = either a member of :data:`PROTECTED_PATHS` or any non-GET method
    on a ``/api/v1/*`` path. The non-GET rule is defence in depth so future write
    endpoints inherit auth before they are added to the explicit set.
    """

    if path in PROTECTED_PATHS:
        return True
    return method != "GET" and path.startswith("/api/v1/")


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Enforce ``X-API-Key`` on protected paths in private mode.

    Behaviour matrix:

    * Public mode → pass through (writes already 403'd by ``public_mode_guard``).
    * Non-protected path → pass through.
    * Private mode + ``api_key=None`` → pass through (dev mode; warning at startup).
    * Private mode + ``api_key`` set + missing header → 401 ``Missing X-API-Key header``.
    * Private mode + ``api_key`` set + wrong header → 401 ``Invalid X-API-Key header``.
    * Private mode + ``api_key`` set + correct header → pass through.

    The middleware reads the live ``settings`` module attribute on every request so
    that the ``sys.modules`` patch pattern used in the test fixtures is honoured.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings: Settings = self._current_settings()

        if settings.public_mode:
            return await call_next(request)

        path: str = request.url.path
        method: str = request.method
        if not is_protected_path(method, path):
            return await call_next(request)

        if settings.api_key is None:
            return await call_next(request)

        configured_key: str = settings.api_key.get_secret_value()
        supplied: str | None = request.headers.get(API_KEY_HEADER)
        request_id: str = get_request_id()

        if supplied is None:
            logger.warning(
                "Rejected request: missing X-API-Key (method=%s path=%s request_id=%s)",
                method,
                path,
                request_id,
            )
            return _problem_response(
                detail=f"Missing {API_KEY_HEADER} header.",
                request_id=request_id,
                type_uri="tag:csm-set,2026:problem/missing-api-key",
                title="Missing API key",
            )

        if not secrets.compare_digest(supplied, configured_key):
            logger.warning(
                "Rejected request: invalid X-API-Key (method=%s path=%s request_id=%s)",
                method,
                path,
                request_id,
            )
            return _problem_response(
                detail=f"Invalid {API_KEY_HEADER} header.",
                request_id=request_id,
                type_uri="tag:csm-set,2026:problem/invalid-api-key",
                title="Invalid API key",
            )

        return await call_next(request)

    @staticmethod
    def _current_settings() -> Settings:
        """Read the live settings instance via :mod:`sys.modules`.

        Mirrors the pattern used by ``api.routers.notebooks._settings`` so that
        test fixtures patching ``sys.modules['csm.config.settings'].settings``
        are honoured without an import-time binding.
        """

        import sys

        module = sys.modules["csm.config.settings"]
        return module.settings  # type: ignore[no-any-return]


def _problem_response(*, detail: str, request_id: str, type_uri: str, title: str) -> JSONResponse:
    """Return a 401 JSON response as an RFC 7807 problem detail."""

    return JSONResponse(
        status_code=401,
        content={
            "type": type_uri,
            "title": title,
            "status": 401,
            "detail": detail,
            "instance": None,
            "request_id": request_id,
        },
        headers={"Content-Type": "application/problem+json"},
    )


__all__: list[str] = [
    "API_KEY_HEADER",
    "APIKeyMiddleware",
    "PROTECTED_PATHS",
    "is_protected_path",
]
