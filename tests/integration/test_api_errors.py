"""Integration tests for Phase 5.8 — Error shape uniformity."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

RFC7807_FIELDS: set[str] = {"type", "title", "status", "detail", "instance", "request_id"}
PROBLEM_JSON: str = "application/problem+json"


def _assert_rfc7807_shape(body: dict[str, object], *, status: int) -> None:
    """Assert the response body is a valid RFC 7807 problem detail."""
    missing = RFC7807_FIELDS - set(body.keys())
    assert not missing, f"Missing RFC 7807 fields: {missing}"
    assert body["status"] == status
    assert isinstance(body["type"], str) and len(body["type"]) > 0
    assert isinstance(body["title"], str)
    assert isinstance(body["detail"], str)
    assert body["request_id"] is not None


class TestPublicMode403:
    def test_403_error_shape(self, public_client: TestClient) -> None:
        resp = public_client.post("/api/v1/data/refresh")
        assert resp.status_code == 403
        body = resp.json()
        _assert_rfc7807_shape(body, status=403)
        assert body["type"] == "tag:csm-set,2026:problem/public-mode-disabled"
        assert resp.headers["Content-Type"] == PROBLEM_JSON

    def test_403_includes_request_id_header_match(
        self, public_client: TestClient
    ) -> None:
        resp = public_client.post("/api/v1/backtest/run")
        body = resp.json()
        assert resp.headers["x-request-id"] == body["request_id"]


class TestPrivateMode401:
    def test_401_error_shape(
        self, private_client_with_key: tuple[TestClient, str]
    ) -> None:
        client, _ = private_client_with_key
        resp = client.post("/api/v1/data/refresh")
        assert resp.status_code == 401
        body = resp.json()
        _assert_rfc7807_shape(body, status=401)
        assert body["type"] == "tag:csm-set,2026:problem/missing-api-key"
        assert resp.headers["Content-Type"] == PROBLEM_JSON

    def test_401_wrong_key_shape(
        self, private_client_with_key: tuple[TestClient, str]
    ) -> None:
        client, _ = private_client_with_key
        resp = client.post(
            "/api/v1/data/refresh", headers={"X-API-Key": "wrong"}
        )
        assert resp.status_code == 401
        body = resp.json()
        _assert_rfc7807_shape(body, status=401)
        assert body["type"] == "tag:csm-set,2026:problem/invalid-api-key"


class TestNotFound404:
    def test_404_starlette_routing(self, public_client: TestClient) -> None:
        resp = public_client.get("/nonexistent-path")
        assert resp.status_code == 404
        body = resp.json()
        _assert_rfc7807_shape(body, status=404)
        assert body["type"] == "tag:csm-set,2026:problem/not-found"
        assert resp.headers["Content-Type"] == PROBLEM_JSON

    def test_404_job_not_found(
        self, private_client_with_key: tuple[TestClient, str]
    ) -> None:
        client, key = private_client_with_key
        resp = client.get(
            "/api/v1/jobs/nonexistent-job-id",
            headers={"X-API-Key": key},
        )
        assert resp.status_code == 404
        body = resp.json()
        _assert_rfc7807_shape(body, status=404)


class TestMalformed500:
    def test_malformed_json_triggers_500(
        self, public_client: TestClient, tmp_results_malformed: Path
    ) -> None:
        """Malformed public-mode JSON triggers a 500 from the router layer."""
        resp = public_client.get("/api/v1/signals/latest")
        assert resp.status_code == 500
        body = resp.json()
        assert body["detail"] == "Signals payload is malformed JSON."
        assert body["request_id"] is not None
        assert resp.headers["Content-Type"] == PROBLEM_JSON

    def test_router_500_includes_request_id(
        self, public_client: TestClient, tmp_results_malformed: Path
    ) -> None:
        resp = public_client.get("/api/v1/portfolio/current")
        assert resp.status_code == 500
        body = resp.json()
        assert body["request_id"] is not None
        assert resp.headers["Content-Type"] == PROBLEM_JSON


class TestCrossCutting:
    def test_all_error_paths_have_request_id(
        self,
        public_client: TestClient,
        private_client_with_key: tuple[TestClient, str],
    ) -> None:
        client, key = private_client_with_key

        # 404
        r = public_client.get("/nonexistent")
        assert r.json()["request_id"] is not None
        # 403
        r = public_client.post("/api/v1/data/refresh")
        assert r.json()["request_id"] is not None
        # 401
        r = client.post("/api/v1/data/refresh")
        assert r.json()["request_id"] is not None
        # 404 job
        r = client.get("/api/v1/jobs/no-such-job", headers={"X-API-Key": key})
        assert r.json()["request_id"] is not None

    def test_request_id_header_matches_body_on_error(
        self, public_client: TestClient
    ) -> None:
        resp = public_client.get("/nonexistent-path")
        body = resp.json()
        assert resp.headers["x-request-id"] == body["request_id"]
