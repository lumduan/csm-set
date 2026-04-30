"""Unit tests for Phase 5.1 — App Factory & Lifespan.

These tests validate the NEW Phase 5.1 deliverables:
- app.version sourced from csm.__version__
- RequestIDMiddleware (ULID per request, X-Request-ID header, contextvar)
- JobRegistry instantiated in lifespan
- Exception handler stub (request_id in error body)

Public-mode guard behaviour is already covered by integration tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from api.jobs import JobRegistry
from api.logging import REQUEST_ID_CTX
from fastapi.testclient import TestClient

from csm import __version__


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Create a FastAPI TestClient with temp data / results directories."""
    from api.main import app  # noqa: PLC0415

    monkeypatch.setenv("CSM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CSM_RESULTS_DIR", str(tmp_path / "results"))

    with TestClient(app) as c:
        yield c


class TestAppVersion:
    def test_app_version_matches_csm_version(self, client: TestClient) -> None:
        from api.main import app  # noqa: PLC0415

        assert app.version == __version__

    def test_openapi_info_version(self, client: TestClient) -> None:
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        assert resp.json()["info"]["version"] == __version__


class TestJobRegistryLifespan:
    def test_lifespan_creates_job_registry_on_state(self, client: TestClient) -> None:
        from api.main import app  # noqa: PLC0415

        assert hasattr(app.state, "jobs")
        assert isinstance(app.state.jobs, JobRegistry)

    def test_job_registry_get_returns_none_for_unknown(self, client: TestClient) -> None:
        from api.main import app  # noqa: PLC0415

        assert app.state.jobs.get("nonexistent") is None


class TestRequestID:
    def test_x_request_id_header_present(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert "x-request-id" in resp.headers

    def test_request_ids_differ_per_request(self, client: TestClient) -> None:
        resp1 = client.get("/health")
        resp2 = client.get("/health")
        assert resp1.headers["x-request-id"] != resp2.headers["x-request-id"]

    def test_request_id_contextvar_reset_between_requests(self, client: TestClient) -> None:
        client.get("/health")
        assert REQUEST_ID_CTX.get() == "N/A"

    def test_request_id_is_ulid_format(self, client: TestClient) -> None:
        resp = client.get("/health")
        rid = resp.headers["x-request-id"]
        assert len(rid) == 26  # ULID is 26 chars
        assert rid.isalnum()  # ULID uses Crockford base32


class TestErrorHandlers:
    def test_http_404_includes_request_id(self, client: TestClient) -> None:
        resp = client.get("/nonexistent-path")
        assert resp.status_code == 404
        body = resp.json()
        assert "request_id" in body

    def test_http_exception_detail_preserved(self, client: TestClient) -> None:
        resp = client.get("/nonexistent-path")
        body = resp.json()
        assert "detail" in body


class TestHealthEndpoint:
    def test_health_returns_version(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["version"] == __version__

    def test_health_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.json()["status"] == "ok"
