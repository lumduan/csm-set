"""Integration tests for GET /api/v1/universe."""

from __future__ import annotations

from api.schemas.universe import UniverseSnapshot
from fastapi.testclient import TestClient


class TestUniversePublic:
    """Public-mode universe endpoint tests."""

    def test_universe_public_returns_404_when_store_empty(self, public_client: TestClient) -> None:
        """Public mode with empty store returns 404 problem-detail."""
        resp = public_client.get("/api/v1/universe")
        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body
        assert "request_id" in body

    def test_universe_public_idempotent(self, public_client: TestClient) -> None:
        """Multiple identical requests return consistent results."""
        resp1 = public_client.get("/api/v1/universe")
        resp2 = public_client.get("/api/v1/universe")
        assert resp1.status_code == resp2.status_code
        if resp1.status_code == 200:
            assert resp1.json() == resp2.json()


class TestUniversePrivate:
    """Private-mode universe endpoint tests."""

    def test_universe_private_returns_200_with_data(self, private_client: TestClient) -> None:
        """Private mode with populated store returns 200 and valid schema."""
        resp = private_client.get("/api/v1/universe")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 3
        symbols = {item["symbol"] for item in body["items"]}
        assert symbols == {"SET001", "SET002", "SET003"}

    def test_universe_private_response_schema(self, private_client: TestClient) -> None:
        """Response body parses cleanly into UniverseSnapshot."""
        resp = private_client.get("/api/v1/universe")
        assert resp.status_code == 200
        snapshot = UniverseSnapshot.model_validate(resp.json())
        assert snapshot.count == len(snapshot.items)

    def test_universe_private_404_on_empty_store(self, empty_store_client: TestClient) -> None:
        """Empty store returns 404 with problem-detail body."""
        resp = empty_store_client.get("/api/v1/universe")
        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body
        assert "request_id" in body


class TestUniverseETag:
    """ETag caching tests for the universe endpoint."""

    def test_etag_header_present(self, private_client: TestClient) -> None:
        """Response includes an ETag header."""
        resp = private_client.get("/api/v1/universe")
        assert resp.status_code == 200
        assert "etag" in resp.headers
        etag = resp.headers["etag"]
        assert etag.startswith('W/"')

    def test_etag_304_roundtrip(self, private_client: TestClient) -> None:
        """If-None-Match with matching ETag returns 304 Not Modified."""
        resp1 = private_client.get("/api/v1/universe")
        assert resp1.status_code == 200
        etag = resp1.headers["etag"]

        resp2 = private_client.get(
            "/api/v1/universe",
            headers={"If-None-Match": etag},
        )
        assert resp2.status_code == 304
        assert resp2.content == b""
        assert resp2.headers.get("etag") == etag

    def test_etag_stale_returns_200(self, private_client: TestClient) -> None:
        """Non-matching If-None-Match returns 200 with fresh data."""
        resp = private_client.get(
            "/api/v1/universe",
            headers={"If-None-Match": 'W/"nonexistent-hash"'},
        )
        assert resp.status_code == 200
