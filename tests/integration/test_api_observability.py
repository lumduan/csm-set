"""Integration tests for observability: structured access logs and request-id propagation."""

from __future__ import annotations

import io
import json
import logging

import pytest
from fastapi.testclient import TestClient

from api.logging import JsonFormatter


def _capture_json_logs(caplog: pytest.LogCaptureFixture) -> io.StringIO:
    """Attach a JsonFormatter handler to capture structured log output."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    handler.setLevel(logging.INFO)
    logging.getLogger("api.logging").addHandler(handler)
    return buf


class TestAccessLogContent:
    """Verify the AccessLogMiddleware emits one structured log line per request."""

    def test_access_log_line_contains_required_fields(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Each access log line must contain method, path, status, duration_ms, request_id."""
        buf = _capture_json_logs(caplog)
        client.get("/health")
        handler = logging.getLogger("api.logging").handlers[-1]
        handler.flush()
        access_objs = [
            json.loads(line)
            for line in buf.getvalue().splitlines()
            if '"msg": "access"' in line
        ]
        logging.getLogger("api.logging").removeHandler(handler)
        assert len(access_objs) >= 1, "Expected at least one JSON access log line"
        for obj in access_objs:
            for field in ("method", "path", "status", "duration_ms", "request_id"):
                assert field in obj, f"Access log missing field: {field}"
            assert isinstance(obj["duration_ms"], (int, float))

    def test_request_id_in_log_matches_response_header(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The request_id in the JSON access log must match the X-Request-ID header."""
        buf = _capture_json_logs(caplog)
        resp = client.get("/health")
        header_id = resp.headers.get("X-Request-ID")
        assert header_id, "Missing X-Request-ID header"

        handler = logging.getLogger("api.logging").handlers[-1]
        handler.flush()
        access_objs = [
            json.loads(line)
            for line in buf.getvalue().splitlines()
            if '"msg": "access"' in line
        ]
        logging.getLogger("api.logging").removeHandler(handler)
        assert len(access_objs) >= 1
        log_request_id = access_objs[-1].get("request_id")
        assert log_request_id == header_id, (
            f"Log request_id {log_request_id} != header {header_id}"
        )

    def test_one_access_log_line_per_request(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """N requests should produce at least N access log lines."""
        buf = _capture_json_logs(caplog)
        n = 3
        for _ in range(n):
            client.get("/health")

        handler = logging.getLogger("api.logging").handlers[-1]
        handler.flush()
        access_lines = [
            line for line in buf.getvalue().splitlines() if '"msg": "access"' in line
        ]
        logging.getLogger("api.logging").removeHandler(handler)
        assert len(access_lines) >= n, (
            f"Expected >= {n} access log lines, got {len(access_lines)}"
        )

    def test_access_log_fields_are_set_on_record(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The middleware sets method/path/status/duration_ms as record attrs via extra=."""
        caplog.set_level(logging.INFO, logger="api.logging")
        client.get("/health")
        access_lines = [
            r for r in caplog.records
            if r.name == "api.logging" and getattr(r, "msg", "") == "access"
        ]
        assert len(access_lines) >= 1
        record = access_lines[-1]
        for field in ("method", "path", "status", "duration_ms"):
            assert hasattr(record, field), f"Access log record missing field: {field}"


class TestRequestIDInErrorResponses:
    """The request_id from the contextvar appears in RFC 7807 error bodies."""

    def test_404_includes_request_id(self, client: TestClient) -> None:
        resp = client.get("/api/v1/signals/nonexistent")
        assert resp.status_code == 404
        body = resp.json()
        assert "request_id" in body, f"Missing request_id in 404 body: {body}"

    def test_403_includes_request_id(self, client: TestClient) -> None:
        resp = client.post("/api/v1/data/refresh")
        assert resp.status_code == 403
        body = resp.json()
        assert "request_id" in body, f"Missing request_id in 403 body: {body}"


class TestXRequestIDHeader:
    """Every response must carry an X-Request-ID header."""

    def test_health_has_request_id(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert "X-Request-ID" in resp.headers

    def test_openapi_has_request_id(self, client: TestClient) -> None:
        resp = client.get("/openapi.json")
        assert "X-Request-ID" in resp.headers

    def test_api_endpoint_has_request_id(self, client: TestClient) -> None:
        resp = client.get("/api/v1/universe")
        assert "X-Request-ID" in resp.headers
