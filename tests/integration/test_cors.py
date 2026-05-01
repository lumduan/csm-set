"""Integration tests for Phase 6.1 — CORS middleware behaviour."""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestCORSPublicMode:
    def test_options_preflight_returns_cors_headers(self, public_client: TestClient) -> None:
        """OPTIONS preflight returns Access-Control-Allow-* headers."""
        resp = public_client.options(
            "/api/v1/signals/latest",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert (
            resp.headers["access-control-allow-origin"] == "*"
            or resp.headers["access-control-allow-origin"] == "http://example.com"
        )
        assert "GET" in resp.headers["access-control-allow-methods"]

    def test_get_returns_cors_allow_origin_header(self, public_client: TestClient) -> None:
        """GET response includes access-control-allow-origin header."""
        resp = public_client.get(
            "/api/v1/signals/latest",
            headers={"Origin": "http://example.com"},
        )
        assert resp.status_code in (200, 404)
        assert "access-control-allow-origin" in resp.headers

    def test_options_preflight_health_endpoint(self, public_client: TestClient) -> None:
        """OPTIONS preflight on /health also returns CORS headers."""
        resp = public_client.options(
            "/health",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert "access-control-allow-origin" in resp.headers

    def test_cors_headers_allow_all_request_headers(self, public_client: TestClient) -> None:
        """CORS configuration permits arbitrary request headers."""
        resp = public_client.options(
            "/api/v1/signals/latest",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-api-key,content-type",
            },
        )
        assert resp.status_code == 200
        assert "access-control-allow-headers" in resp.headers

    def test_credentials_not_allowed(self, public_client: TestClient) -> None:
        """Access-Control-Allow-Credentials must be absent or false."""
        resp = public_client.options(
            "/api/v1/signals/latest",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        allow_creds = resp.headers.get("access-control-allow-credentials")
        assert allow_creds is None or allow_creds.lower() == "false"


class TestCORSWriteEndpoints:
    def test_options_preflight_write_endpoint_blocked_in_public(
        self, public_client: TestClient
    ) -> None:
        """OPTIONS preflight on write endpoints returns 403 in public mode."""
        resp = public_client.options(
            "/api/v1/data/refresh",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.status_code == 403
