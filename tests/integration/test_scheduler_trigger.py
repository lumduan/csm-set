"""Integration tests for Phase 5.5 — Scheduler manual trigger endpoint.

Validates POST /api/v1/scheduler/run/{job_id} lifecycle, public-mode
gating, job-id validation, and marker file persistence.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pandas as pd
from fastapi.testclient import TestClient


class TestManualTrigger:
    """POST /api/v1/scheduler/run/{job_id} endpoint behaviour."""

    def test_trigger_daily_refresh_returns_accepted(
        self, private_client: TestClient
    ) -> None:
        resp = private_client.post("/api/v1/scheduler/run/daily_refresh")
        assert resp.status_code == 200
        body = resp.json()
        assert "job_id" in body
        assert body["status"] == "accepted"

    def test_trigger_invalid_job_id_returns_400(
        self, private_client: TestClient
    ) -> None:
        resp = private_client.post("/api/v1/scheduler/run/nonexistent_job")
        assert resp.status_code == 400
        body = resp.json()
        assert "detail" in body
        assert "nonexistent_job" in body["detail"]

    def test_trigger_blocked_in_public_mode(self, client: TestClient) -> None:
        resp = client.post("/api/v1/scheduler/run/daily_refresh")
        assert resp.status_code == 403
        assert "Disabled in public mode" in resp.json()["detail"]

    def test_trigger_poll_to_terminal(self, private_client: TestClient) -> None:
        submit_resp = private_client.post("/api/v1/scheduler/run/daily_refresh")
        assert submit_resp.status_code == 200
        job_id: str = submit_resp.json()["job_id"]

        terminal_states = {"succeeded", "failed", "cancelled"}
        for _ in range(50):
            resp = private_client.get(f"/api/v1/jobs/{job_id}")
            assert resp.status_code == 200
            status: str = resp.json()["status"]
            if status in terminal_states:
                break
            time.sleep(0.1)
        else:
            raise AssertionError(
                f"Scheduler trigger job {job_id} did not reach terminal state"
            )

        body = resp.json()
        assert body["job_id"] == job_id
        assert body["kind"] == "data_refresh"
        assert body["status"] in terminal_states
        assert body["started_at"] is not None
        assert body["finished_at"] is not None

    def test_trigger_writes_marker_file_on_success(
        self, private_client: TestClient, tmp_path: Path
    ) -> None:
        dates = pd.date_range("2024-01-01", periods=3, freq="B", tz="Asia/Bangkok")
        ohlcv_frame = pd.DataFrame(
            {
                "open": [100.0] * 3,
                "high": [101.0] * 3,
                "low": [99.0] * 3,
                "close": [100.5] * 3,
                "volume": [1_000_000.0] * 3,
            },
            index=dates,
        )
        # private_store has SET001, SET002, SET003 — match all to get failures=0.
        fetched = {"SET001": ohlcv_frame, "SET002": ohlcv_frame, "SET003": ohlcv_frame}
        with patch("api.scheduler.jobs.OHLCVLoader") as MockLoader:
            mock_loader = MockLoader.return_value
            mock_loader.fetch_batch = AsyncMock(return_value=fetched)

            with patch("api.scheduler.jobs.FeaturePipeline"):
                submit_resp = private_client.post("/api/v1/scheduler/run/daily_refresh")
                assert submit_resp.status_code == 200
                job_id: str = submit_resp.json()["job_id"]

                for _ in range(50):
                    resp = private_client.get(f"/api/v1/jobs/{job_id}")
                    assert resp.status_code == 200
                    if resp.json()["status"] in {"succeeded", "failed"}:
                        break
                    time.sleep(0.1)

        body = resp.json()
        assert body["status"] == "succeeded"

        marker_path = tmp_path / "results" / ".tmp" / "last_refresh.json"
        assert marker_path.is_file()
        marker = json.loads(marker_path.read_text())
        assert marker["symbols_fetched"] == 3
        assert marker["failures"] == 0
        assert "timestamp" in marker
        assert "duration_seconds" in marker
