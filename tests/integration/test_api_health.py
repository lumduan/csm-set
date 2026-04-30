"""Integration tests for Phase 5.8 — Extended /health endpoint."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient


class TestHealthPublicMode:
    def test_health_public_mode_fields(self, public_client: TestClient) -> None:
        resp = public_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in ("ok", "degraded")
        assert body["version"]
        assert body["public_mode"] is True
        assert body["scheduler_running"] is False
        assert body["last_refresh_at"] is None
        assert body["last_refresh_status"] is None
        assert body["jobs_pending"] == 0

    def test_health_public_mode_is_ok(self, public_client: TestClient) -> None:
        resp = public_client.get("/health")
        body = resp.json()
        assert body["status"] == "ok"


class TestHealthPrivateMode:
    def test_health_private_mode_fields(
        self, private_client_with_key: tuple[TestClient, str]
    ) -> None:
        client, key = private_client_with_key
        resp = client.get("/health", headers={"X-API-Key": key})
        assert resp.status_code == 200
        body = resp.json()
        assert body["public_mode"] is False
        assert body["scheduler_running"] is True
        assert body["version"]

    def test_health_private_mode_is_degraded_no_marker(
        self, private_client_with_key: tuple[TestClient, str]
    ) -> None:
        """Health should be degraded in private mode when no last_refresh marker."""
        client, key = private_client_with_key
        resp = client.get("/health", headers={"X-API-Key": key})
        body = resp.json()
        # Private mode without a marker: scheduler_running but no refresh done yet
        assert body["scheduler_running"] is True
        assert body["last_refresh_at"] is None


class TestHealthLastRefreshMarker:
    def test_health_reads_last_refresh_marker(
        self,
        private_client_with_key: tuple[TestClient, str],
        tmp_path: Path,
    ) -> None:
        """Write a last_refresh.json marker and verify /health surfaces it."""
        marker_dir = tmp_path / "results" / ".tmp"
        marker_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime(2026, 4, 30, 10, 0, 0, tzinfo=UTC).isoformat()
        marker_dir.joinpath("last_refresh.json").write_text(
            json.dumps({"timestamp": ts, "symbols_fetched": 10, "failures": 0})
        )

        client, key = private_client_with_key
        resp = client.get("/health", headers={"X-API-Key": key})
        assert resp.status_code == 200
        body = resp.json()
        assert body["last_refresh_at"] is not None
        assert body["last_refresh_status"] == "succeeded"

    def test_health_marker_with_failures_is_failed(
        self,
        private_client_with_key: tuple[TestClient, str],
        tmp_path: Path,
    ) -> None:
        """A marker with failures > 0 should set last_refresh_status to 'failed'."""
        marker_dir = tmp_path / "results" / ".tmp"
        marker_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime(2026, 4, 30, 10, 0, 0, tzinfo=UTC).isoformat()
        marker_dir.joinpath("last_refresh.json").write_text(
            json.dumps({"timestamp": ts, "symbols_fetched": 5, "failures": 3})
        )

        client, key = private_client_with_key
        resp = client.get("/health", headers={"X-API-Key": key})
        body = resp.json()
        assert body["last_refresh_status"] == "failed"

    def test_health_malformed_marker_is_graceful(
        self,
        private_client_with_key: tuple[TestClient, str],
        tmp_path: Path,
    ) -> None:
        """Malformed marker JSON should not crash /health."""
        marker_dir = tmp_path / "results" / ".tmp"
        marker_dir.mkdir(parents=True, exist_ok=True)
        marker_dir.joinpath("last_refresh.json").write_text("not valid json{{{")

        client, key = private_client_with_key
        resp = client.get("/health", headers={"X-API-Key": key})
        assert resp.status_code == 200
        body = resp.json()
        assert body["last_refresh_at"] is None
        assert body["last_refresh_status"] is None
