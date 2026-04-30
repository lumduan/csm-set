"""Integration tests for API public-mode behavior."""

from pathlib import Path

from fastapi.testclient import TestClient


def test_health_public_mode(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.json()["public_mode"] is True


def test_data_refresh_blocked_in_public_mode(client: TestClient) -> None:
    resp = client.post("/api/v1/data/refresh")
    assert resp.status_code == 403


def test_data_refresh_returns_job_id_in_private_mode(
    private_client: TestClient,
) -> None:
    """Phase 5.4: data refresh returns immediately with a job_id, not blocking."""
    resp = private_client.post("/api/v1/data/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert "job_id" in body
    assert body["status"] == "accepted"


def test_backtest_run_blocked_in_public_mode(client: TestClient) -> None:
    resp = client.post("/api/v1/backtest/run", json={})
    assert resp.status_code == 403


def test_jobs_list_blocked_in_public_mode(client: TestClient) -> None:
    """Phase 5.4: GET /api/v1/jobs is blocked in public mode."""
    resp = client.get("/api/v1/jobs")
    assert resp.status_code == 403


def test_signals_latest_serves_results_json_in_public_mode(
    client: TestClient,
    tmp_results: Path,
) -> None:
    resp = client.get("/api/v1/signals/latest")
    assert resp.status_code == 200
