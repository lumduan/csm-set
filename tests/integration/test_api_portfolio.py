"""Integration tests for GET /api/v1/portfolio/current."""

from __future__ import annotations

from api.schemas.portfolio import PortfolioSnapshot
from fastapi.testclient import TestClient


class TestPortfolioPublic:
    """Public-mode portfolio endpoint tests."""

    def test_portfolio_public_returns_200(self, public_client: TestClient) -> None:
        """Public mode with fixture summary.json returns 200."""
        resp = public_client.get("/api/v1/portfolio/current")
        assert resp.status_code == 200
        body = resp.json()
        assert "as_of" in body
        assert "holdings" in body
        assert "summary_metrics" in body
        assert "regime" in body
        assert "breaker_state" in body
        assert "equity_fraction" in body

    def test_portfolio_public_response_schema(self, public_client: TestClient) -> None:
        """Response body parses into PortfolioSnapshot Pydantic model."""
        resp = public_client.get("/api/v1/portfolio/current")
        assert resp.status_code == 200
        snapshot = PortfolioSnapshot.model_validate(resp.json())
        assert snapshot.regime == "NEUTRAL"
        assert snapshot.breaker_state == "NORMAL"
        assert snapshot.equity_fraction == 1.0
        assert isinstance(snapshot.holdings, list)
        assert isinstance(snapshot.summary_metrics, dict)

    def test_portfolio_public_idempotent(self, public_client: TestClient) -> None:
        """Multiple identical requests return consistent results."""
        resp1 = public_client.get("/api/v1/portfolio/current")
        resp2 = public_client.get("/api/v1/portfolio/current")
        assert resp1.status_code == resp2.status_code
        if resp1.status_code == 200:
            assert resp1.json() == resp2.json()


class TestPortfolioPrivate:
    """Private-mode portfolio endpoint tests."""

    def test_portfolio_private_returns_200_with_holdings(self, private_client: TestClient) -> None:
        """Private mode with populated store returns 200 with holdings."""
        resp = private_client.get("/api/v1/portfolio/current")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["holdings"]) == 2
        symbols = {h["symbol"] for h in body["holdings"]}
        assert symbols == {"SET001", "SET002"}

    def test_portfolio_private_response_schema(self, private_client: TestClient) -> None:
        """Response body parses into PortfolioSnapshot Pydantic model."""
        resp = private_client.get("/api/v1/portfolio/current")
        assert resp.status_code == 200
        snapshot = PortfolioSnapshot.model_validate(resp.json())
        assert len(snapshot.holdings) == 2
        assert all(0.0 <= h.weight <= 1.0 for h in snapshot.holdings)

    def test_portfolio_private_surfaces_regime_and_breaker(
        self, private_client: TestClient
    ) -> None:
        """Response includes regime, breaker_state, and equity_fraction from stored state."""
        resp = private_client.get("/api/v1/portfolio/current")
        assert resp.status_code == 200
        body = resp.json()
        assert body["regime"] == "BULL"
        assert body["breaker_state"] == "NORMAL"
        assert body["equity_fraction"] == 1.0

    def test_portfolio_private_404_on_empty_store(self, empty_store_client: TestClient) -> None:
        """Empty store returns 404 with problem-detail body."""
        resp = empty_store_client.get("/api/v1/portfolio/current")
        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body
        assert "request_id" in body


class TestPortfolioETag:
    """ETag caching tests for the portfolio endpoint."""

    def test_etag_header_present(self, private_client: TestClient) -> None:
        """Response includes an ETag header."""
        resp = private_client.get("/api/v1/portfolio/current")
        assert resp.status_code == 200
        assert "etag" in resp.headers
        etag = resp.headers["etag"]
        assert etag.startswith('W/"')

    def test_etag_304_roundtrip(self, private_client: TestClient) -> None:
        """If-None-Match with matching ETag returns 304 Not Modified."""
        resp1 = private_client.get("/api/v1/portfolio/current")
        assert resp1.status_code == 200
        etag = resp1.headers["etag"]

        resp2 = private_client.get(
            "/api/v1/portfolio/current",
            headers={"If-None-Match": etag},
        )
        assert resp2.status_code == 304
        assert resp2.content == b""
        assert resp2.headers.get("etag") == etag

    def test_etag_stale_returns_200(self, private_client: TestClient) -> None:
        """Non-matching If-None-Match returns 200 with fresh data."""
        resp = private_client.get(
            "/api/v1/portfolio/current",
            headers={"If-None-Match": 'W/"nonexistent-hash"'},
        )
        assert resp.status_code == 200

    def test_etag_consistent_for_same_data(self, public_client: TestClient) -> None:
        """Identical payloads (public mode, deterministic) produce the same ETag."""
        resp1 = public_client.get("/api/v1/portfolio/current")
        resp2 = public_client.get("/api/v1/portfolio/current")
        if resp1.status_code == 200 and resp2.status_code == 200:
            assert resp1.headers["etag"] == resp2.headers["etag"]
