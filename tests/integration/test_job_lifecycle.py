"""Integration tests for Phase 5.4 — Job lifecycle (submit, poll, persist)."""

from __future__ import annotations

import time
from pathlib import Path

from api.jobs import JobRegistry, JobStatus
from fastapi.testclient import TestClient


class TestDataRefreshJob:
    """Submit a data refresh, poll until completion, verify."""

    def test_submit_returns_accepted(self, private_client: TestClient) -> None:
        """POST /api/v1/data/refresh returns a job_id with status='accepted'."""
        resp = private_client.post("/api/v1/data/refresh")
        assert resp.status_code == 200
        body = resp.json()
        assert "job_id" in body
        assert body["status"] == "accepted"

    def test_poll_until_terminal(self, private_client: TestClient) -> None:
        """Poll GET /api/v1/jobs/{job_id} until the job reaches a terminal state."""
        submit_resp = private_client.post("/api/v1/data/refresh")
        assert submit_resp.status_code == 200
        job_id: str = submit_resp.json()["job_id"]

        terminal_states = {"succeeded", "failed", "cancelled"}
        for _ in range(50):  # 5 s timeout with 0.1 s sleep
            resp = private_client.get(f"/api/v1/jobs/{job_id}")
            assert resp.status_code == 200
            status: str = resp.json()["status"]
            if status in terminal_states:
                break
            time.sleep(0.1)
        else:
            raise AssertionError(f"Job {job_id} did not reach a terminal state within timeout")

        body = resp.json()
        assert body["job_id"] == job_id
        assert body["kind"] == "data_refresh"
        assert body["status"] in terminal_states
        assert body["started_at"] is not None
        assert body["finished_at"] is not None

    def test_job_not_found_returns_404(self, private_client: TestClient) -> None:
        """GET /api/v1/jobs/nonexistent returns 404."""
        resp = private_client.get("/api/v1/jobs/nonexistent-job-id")
        assert resp.status_code == 404


class TestBacktestJobLifecycle:
    """Submit a backtest, poll, verify the lifecycle."""

    def test_submit_backtest(self, private_client: TestClient) -> None:
        """POST /api/v1/backtest/run returns accepted."""
        resp = private_client.post("/api/v1/backtest/run", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert "job_id" in body
        assert body["status"] == "accepted"

    def test_poll_backtest_to_terminal(self, private_client: TestClient) -> None:
        """Backtest job reaches a terminal state."""
        submit_resp = private_client.post("/api/v1/backtest/run", json={})
        assert submit_resp.status_code == 200
        job_id: str = submit_resp.json()["job_id"]

        terminal_states = {"succeeded", "failed", "cancelled"}
        for _ in range(100):  # 10 s timeout for potentially slow backtest
            resp = private_client.get(f"/api/v1/jobs/{job_id}")
            assert resp.status_code == 200
            status: str = resp.json()["status"]
            if status in terminal_states:
                break
            time.sleep(0.1)
        else:
            raise AssertionError(f"Backtest job {job_id} did not finish within timeout")

        body = resp.json()
        assert body["status"] in terminal_states
        assert body["kind"] == "backtest_run"

    def test_backtest_blocked_in_public_mode(self, client: TestClient) -> None:
        """POST /api/v1/backtest/run returns 403 in public mode."""
        resp = client.post("/api/v1/backtest/run", json={})
        assert resp.status_code == 403


class TestJobListEndpoint:
    """GET /api/v1/jobs filtering and public-mode gating."""

    def test_list_returns_array(self, private_client: TestClient) -> None:
        """GET /api/v1/jobs returns a JSON array."""
        resp = private_client.get("/api/v1/jobs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_with_kind_filter(self, private_client: TestClient) -> None:
        """Filtering by kind only returns matching jobs."""
        # Submit one of each kind
        private_client.post("/api/v1/data/refresh")
        resp = private_client.get("/api/v1/jobs?kind=data_refresh")
        assert resp.status_code == 200
        for job in resp.json():
            assert job["kind"] == "data_refresh"

    def test_list_respects_limit(self, private_client: TestClient) -> None:
        """Limit query parameter caps the result count."""
        resp = private_client.get("/api/v1/jobs?limit=1")
        assert resp.status_code == 200
        assert len(resp.json()) <= 1

    def test_list_blocked_in_public_mode(self, client: TestClient) -> None:
        """GET /api/v1/jobs returns 403 in public mode."""
        resp = client.get("/api/v1/jobs")
        assert resp.status_code == 403

    def test_single_job_not_blocked_in_public_mode(self, client: TestClient) -> None:
        """GET /api/v1/jobs/{id} is readable in public mode (returns 404)."""
        resp = client.get("/api/v1/jobs/some-job-id")
        assert resp.status_code == 404


class TestJobListFilters:
    """Exercise kind and status filter branches in JobRegistry.list()."""

    def test_list_with_status_filter(self, private_client: TestClient) -> None:
        """Filtering by status only returns matching jobs."""
        private_client.post("/api/v1/data/refresh")
        resp = private_client.get("/api/v1/jobs?status=accepted")
        assert resp.status_code == 200
        for job in resp.json():
            assert job["status"] == "accepted"

    def test_list_with_kind_and_status_filter(self, private_client: TestClient) -> None:
        """Combined kind+status filter returns intersection."""
        private_client.post("/api/v1/data/refresh")
        resp = private_client.get("/api/v1/jobs?kind=data_refresh&status=accepted")
        assert resp.status_code == 200
        for job in resp.json():
            assert job["kind"] == "data_refresh"
            assert job["status"] == "accepted"


class TestRestartSafety:
    """Verify completed jobs survive registry re-instantiation."""

    def test_persistence_survives_reload(self, private_client: TestClient, tmp_path: Path) -> None:
        """Submit a job, wait for completion, reload registry, confirm record exists."""
        submit_resp = private_client.post("/api/v1/data/refresh")
        assert submit_resp.status_code == 200
        job_id: str = submit_resp.json()["job_id"]

        terminal_states = {"succeeded", "failed", "cancelled"}
        for _ in range(50):
            resp = private_client.get(f"/api/v1/jobs/{job_id}")
            assert resp.status_code == 200
            if resp.json()["status"] in terminal_states:
                break
            time.sleep(0.1)

        # Reload from the same persistence directory used by the lifespan.
        persistence_dir = tmp_path / "results" / ".tmp" / "jobs"
        registry2 = JobRegistry.load_all(persistence_dir)
        restored = registry2.get(job_id)
        assert restored is not None, f"Job {job_id} not found after reload"
        assert restored.status == JobStatus(resp.json()["status"])
        assert restored.job_id == job_id
