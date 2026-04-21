"""Integration tests for API public-mode behavior."""

from pathlib import Path

from fastapi.testclient import TestClient


def test_health_public_mode(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.json()["public_mode"] is True


def test_data_refresh_blocked_in_public_mode(client: TestClient) -> None:
    resp = client.post("/api/v1/data/refresh")
    assert resp.status_code == 403


def test_backtest_run_blocked_in_public_mode(client: TestClient) -> None:
    resp = client.post("/api/v1/backtest/run", json={})
    assert resp.status_code == 403


def test_signals_latest_serves_results_json_in_public_mode(
    client: TestClient,
    tmp_results: Path,
) -> None:
    resp = client.get("/api/v1/signals/latest")
    assert resp.status_code == 200