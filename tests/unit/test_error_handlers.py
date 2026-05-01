"""Unit tests for Phase 5.8 — Error handling and problem-detail responses."""

from __future__ import annotations

from api.errors import (
    ProblemDetailException,
    general_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException


class TestProblemDetailException:
    def test_init_sets_all_fields(self) -> None:
        exc = ProblemDetailException(
            status_code=404,
            type_uri="tag:csm-set,2026:problem/snapshot-not-found",
            title="Snapshot not found",
            detail="Universe data was not found",
        )
        assert exc.status_code == 404
        assert exc.type_uri == "tag:csm-set,2026:problem/snapshot-not-found"
        assert exc.title == "Snapshot not found"
        assert exc.detail == "Universe data was not found"

    def test_str_format(self) -> None:
        exc = ProblemDetailException(
            status_code=500,
            type_uri="tag:csm-set,2026:problem/internal-error",
            title="Internal error",
            detail="Something broke",
        )
        assert str(exc) == "500: Something broke"


class TestHttpExceptionHandler:
    def test_maps_starlette_404_to_problem_detail(self) -> None:
        async def endpoint(request: Request) -> JSONResponse:
            raise HTTPException(status_code=404, detail="Not Found")

        app = _make_app(endpoint)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test")
        assert resp.status_code == 404
        body = resp.json()
        assert body["type"] == "tag:csm-set,2026:problem/not-found"
        assert body["title"] == "Not found"
        assert body["status"] == 404
        assert body["detail"] == "Not Found"
        assert body["instance"] == "/test"
        assert body["request_id"] is not None

    def test_maps_problem_detail_exception_directly(self) -> None:
        async def endpoint(request: Request) -> JSONResponse:
            raise ProblemDetailException(
                status_code=409,
                type_uri="tag:csm-set,2026:problem/job-conflict",
                title="Job conflict",
                detail="Job already in terminal state",
            )

        app = _make_app(endpoint)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test")
        assert resp.status_code == 409
        body = resp.json()
        assert body["type"] == "tag:csm-set,2026:problem/job-conflict"
        assert body["title"] == "Job conflict"
        assert body["status"] == 409

    def test_content_type_is_problem_json(self) -> None:
        async def endpoint(request: Request) -> JSONResponse:
            raise HTTPException(status_code=404, detail="Missing")

        app = _make_app(endpoint)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test")
        assert resp.headers["Content-Type"] == "application/problem+json"

    def test_request_id_in_response_body(self) -> None:
        async def endpoint(request: Request) -> JSONResponse:
            raise HTTPException(status_code=500, detail="Boom")

        app = _make_app(endpoint)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test")
        body = resp.json()
        assert "request_id" in body


class TestValidationExceptionHandler:
    def test_returns_422_problem_detail(self) -> None:
        app = FastAPI()

        @app.post("/test")
        async def endpoint(data: dict[str, int]) -> dict[str, int]:
            return data

        app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/test", json={"bad": "string"})
        assert resp.status_code == 422
        body = resp.json()
        assert body["type"] == "tag:csm-set,2026:problem/validation-error"
        assert body["title"] == "Validation error"
        assert body["status"] == 422
        assert body["instance"] == "/test"
        assert body["request_id"] is not None


class TestGeneralExceptionHandler:
    def test_returns_500_problem_detail(self) -> None:
        async def endpoint(request: Request) -> JSONResponse:
            raise ValueError("Internal bug")

        app = _make_app(endpoint, register_general_handler=True)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test")
        assert resp.status_code == 500
        body = resp.json()
        assert body["type"] == "tag:csm-set,2026:problem/internal-error"
        assert body["title"] == "Internal server error"
        assert body["status"] == 500
        assert body["request_id"] is not None

    def test_does_not_leak_internal_details(self) -> None:
        async def endpoint(request: Request) -> JSONResponse:
            raise ValueError("secret password is hunter2")

        app = _make_app(endpoint, register_general_handler=True)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test")
        body = resp.json()
        assert body["detail"] == "An unexpected error occurred"
        assert "hunter2" not in body["detail"]


def _make_app(
    endpoint: object,
    *,
    register_general_handler: bool = False,
) -> FastAPI:
    """Build a minimal FastAPI app with the exception handlers registered."""

    app = FastAPI()

    @app.get("/test")
    async def _test_endpoint(request: Request) -> JSONResponse:  # type: ignore[no-redef]
        return await endpoint(request)  # type: ignore[union-attr]

    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    if register_general_handler:
        app.add_exception_handler(Exception, general_exception_handler)
    return app
